"""The QGIS companion plugin for the local StudyArea bridge.

This plugin is intentionally a thin UI adapter.  It never sends geometry to
the bridge.  The bridge receives a layer identity and integer FID and obtains
the selected geometry independently over its bounded QGIS MCP connection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .helpers import (
    DRAFT_CRS_AUTHID,
    DRAFT_LAYER_NAME,
    CONTEXT_LAYER_NAME,
    PENDING_PLATFORM_SYNC_SETTINGS_KEY,
    capture_payload,
    capture_result_kind,
    bridge_url,
    build_platform_sync_payload,
    create_pending_platform_sync,
    format_status,
    geometry_bbox_ready,
    load_anchor_config,
    matching_pending_sync_revision,
    parse_pending_platform_sync,
    project_readiness,
    project_id,
    platform_api_base_url,
    qgis_source_feature_reference,
    response_error_text,
    serialize_pending_platform_sync,
    session_token,
    validate_pending_sync_revision,
)

try:  # QGIS imports are available only inside the QGIS Python runtime.
    from qgis.PyQt.QtCore import QByteArray, QSettings, QUrl
    from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest
    from qgis.PyQt.QtWidgets import QAction, QLabel, QMessageBox, QPushButton, QToolBar, QWidget
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsFeatureRequest,
        QgsFields,
        QgsMapLayerType,
        QgsProject,
        QgsVectorFileWriter,
        QgsVectorLayer,
        QgsWkbTypes,
    )
    from qgis.gui import QgsMapToolCapture, QgsMapToolDigitizeFeature

    QGIS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by QGIS, not project Python.
    QGIS_AVAILABLE = False


class UrbanDesignStudyAreaPlugin:
    """Expose the bounded Draw → Use as Study Area workflow in QGIS."""

    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self._toolbar: Any | None = None
        self._status_label: Any | None = None
        self._network: Any | None = None
        self._pending_replies: set[Any] = set()
        self._pending_platform_context: tuple[str, list[dict[str, str]]] | None = None
        self._pending_platform_sync_operation: dict[str, Any] | None = None
        self._pending_platform_sync_load_error: str | None = None
        self._platform_sync_in_flight = False
        self._capture_tool: Any | None = None
        self._actions: list[Any] = []

    def _local_readiness(self) -> tuple[str, str, str]:
        try:
            return project_readiness(QgsProject.instance(), context_layer_name=CONTEXT_LAYER_NAME)
        except Exception as exc:
            return "UNAVAILABLE", "UNAVAILABLE", str(exc)

    def _guard_local_readiness(self) -> dict[str, Any] | None:
        anchor_status, context_status, detail = self._local_readiness()
        if anchor_status != "READY" or context_status != "READY":
            self._error(f"Study Area controls disabled: Anchor {anchor_status}; Context {context_status}. {detail}")
            return None
        try:
            return load_anchor_config()
        except ValueError as exc:
            self._error(str(exc))
            return None

    def initGui(self) -> None:
        """Create the bounded study-area and platform sync controls."""
        self._require_qgis()
        try:
            saved = QSettings().value(PENDING_PLATFORM_SYNC_SETTINGS_KEY, "")
            self._pending_platform_sync_operation = parse_pending_platform_sync(str(saved or ""))
        except ValueError as exc:
            self._pending_platform_sync_load_error = str(exc)
        parent = self.iface.mainWindow()
        self._toolbar = self.iface.addToolBar("Urban Design Study Area")
        self._toolbar.setObjectName("UrbanDesignStudyAreaToolbar")

        draw_action = QAction("Draw Study Area", parent)
        draw_action.triggered.connect(self.draw_study_area)
        use_action = QAction("Use as Study Area", parent)
        use_action.triggered.connect(self.use_as_study_area)
        refresh_action = QAction("Refresh connection status", parent)
        refresh_action.triggered.connect(self.refresh_status)
        sync_action = QAction("Sync to Platform", parent)
        sync_action.setToolTip("Sync selected BAG/OSM source references as a non-binding workspace draft.")
        sync_action.triggered.connect(self.sync_to_platform)

        self._toolbar.addAction(draw_action)
        self._toolbar.addAction(use_action)
        self._toolbar.addAction(refresh_action)
        self._toolbar.addAction(sync_action)
        self._actions = [draw_action, use_action, refresh_action, sync_action]

        self._status_label = QLabel("Backend: checking… | QGIS MCP: checking… | Ladybug: checking…")
        self._status_label.setToolTip("Live local integration readiness")
        self._toolbar.addWidget(self._status_label)
        self._network = QNetworkAccessManager(parent)
        self._update_action_state()
        self.refresh_status()

    def _update_action_state(self) -> None:
        if len(self._actions) < 2:
            return
        anchor_status, context_status, _detail = self._local_readiness()
        ready = anchor_status == "READY" and context_status == "READY"
        try:
            self._actions[0].setEnabled(ready)
            self._actions[1].setEnabled(ready)
        except Exception:
            pass

    def unload(self) -> None:
        """Remove plugin UI and let pending replies finish or be destroyed."""
        for reply in tuple(self._pending_replies):
            try:
                reply.abort()
                reply.deleteLater()
            except Exception:
                pass
        self._pending_replies.clear()
        if self._toolbar is not None:
            try:
                self.iface.removeToolBarIcon(self._toolbar)
                self._toolbar.deleteLater()
            except Exception:
                pass
        self._toolbar = None
        self._status_label = None
        self._network = None

    def draw_study_area(self) -> None:
        """Create/activate the persistent draft layer and enter polygon capture."""
        self._require_qgis()
        if self._guard_local_readiness() is None:
            self._update_action_state()
            return
        try:
            layer = self._get_or_create_draft_layer()
            if layer is None:
                return
            if not layer.isEditable() and not layer.startEditing():
                self._error("Study Area Draft could not enter edit mode.")
                return
            self.iface.setActiveLayer(layer)
            canvas = self.iface.mapCanvas()
            # QGIS 3.40 requires the advanced-digitizing dock widget argument
            # in the capture-tool constructor.  The active layer is already
            # set above; capture therefore writes into this dedicated layer.
            cad_dock = None
            try:
                cad_dock = self.iface.cadDockWidget()
            except Exception:
                pass
            # QgsMapToolCapture is the low-level base class and does not emit
            # a polygonCaptured signal or add a feature to the edit buffer.
            # QgsMapToolDigitizeFeature owns the finish/cancel lifecycle and
            # emits the completed QgsFeature for the companion layer.
            self._capture_tool = QgsMapToolDigitizeFeature(
                canvas,
                cad_dock,
                QgsMapToolCapture.CapturePolygon,
            )
            self._capture_tool.setLayer(layer)
            self._capture_tool.setCheckGeometryType(True)
            # Adding the emitted feature to this dedicated layer keeps the
            # QGIS edit buffer and selection visible to the designer.  The
            # backend still re-reads it through MCP.
            self._capture_tool.digitizingCompleted.connect(
                lambda feature: self._on_feature_captured(layer, feature)
            )
            canvas.setMapTool(self._capture_tool)
            self._message(
                "Study Area Draft is active. Draw one polygon, finish it, and select the saved feature before using it."
            )
        except Exception as exc:
            self._error(f"Unable to start Study Area capture: {exc}")

    def _on_feature_captured(self, layer: Any, feature: Any) -> None:
        """Add one digitized feature to the draft layer's edit buffer."""
        try:
            geometry = feature.geometry()
        except Exception:
            geometry = None
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            self._error("The captured Study Area polygon is empty.")
            return
        captured = QgsFeature(layer.fields())
        captured.setGeometry(geometry)
        if not layer.addFeature(captured):
            self._error("QGIS could not add the captured polygon to Study Area Draft.")
            return
        layer.selectByIds([captured.id()])
        self._message("Polygon added to Study Area Draft. Commit it with Use as Study Area when ready.")

    def use_as_study_area(self) -> None:
        """Commit only the draft layer, validate selection, then post asynchronously."""
        self._require_qgis()
        anchor = self._guard_local_readiness()
        if anchor is None:
            self._update_action_state()
            return
        layer = self._dedicated_layer()
        if layer is None:
            return
        if self._capture_tool is not None:
            try:
                self.iface.mapCanvas().unsetMapTool(self._capture_tool)
            except Exception:
                pass

        selected_before_commit = list(layer.selectedFeatureIds())
        if len(selected_before_commit) != 1:
            self._error(
                f"Select exactly one saved feature in {DRAFT_LAYER_NAME}; found {len(selected_before_commit)}."
            )
            return

        # A pending edit is committed only on the dedicated layer.  No project
        # wide commit action is used, so unrelated human work stays untouched.
        if layer.isEditable():
            if not layer.commitChanges():
                errors = []
                try:
                    errors = list(layer.commitErrors())
                except Exception:
                    pass
                detail = "; ".join(str(error) for error in errors) or "QGIS did not provide details"
                self._error(f"Study Area Draft could not be committed: {detail}")
                return

        selected_ids = list(layer.selectedFeatureIds())
        if len(selected_ids) != 1:
            self._error(
                f"Select exactly one saved feature in {DRAFT_LAYER_NAME}; found {len(selected_ids)}."
            )
            return
        try:
            fid = int(selected_ids[0])
        except (TypeError, ValueError):
            self._error("The selected feature id is not an integer.")
            return
        if fid < 0:
            self._error("The selected feature is not saved yet; draw and commit it first.")
            return

        feature = self._feature_by_fid(layer, fid)
        if feature is None:
            self._error(f"Selected feature {fid} could not be read after commit.")
            return
        geometry = feature.geometry()
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            self._error("The selected Study Area geometry is empty.")
            return
        if geometry.type() != QgsWkbTypes.PolygonGeometry:
            self._error("Study Area must be a polygon geometry.")
            return
        if hasattr(geometry, "isGeosValid") and not geometry.isGeosValid():
            self._error("The selected Study Area polygon is invalid.")
            return
        try:
            bounds = (
                geometry.boundingBox().xMinimum(),
                geometry.boundingBox().yMinimum(),
                geometry.boundingBox().xMaximum(),
                geometry.boundingBox().yMaximum(),
            )
            if not geometry_bbox_ready(bounds, anchor):
                self._error("The selected Study Area is outside the configured M4H drawing anchor.")
                return
        except Exception as exc:
            self._error(f"The selected Study Area anchor check is unresolved: {exc}")
            return

        token = session_token()
        if not token:
            self._error("No launch session token is available; start QGIS with the project launcher.")
            return
        payload = capture_payload(
            instance=self._qgis_instance(),
            layer_id=str(layer.id()),
            fid=fid,
            request_id_value=None,
        )
        self._post_capture(project_id(QgsProject.instance()), payload, token)

    def sync_to_platform(self) -> None:
        """Submit stable selected source identities; the API resolves all data lineage."""
        self._require_qgis()
        if self._network is None:
            self._error("The QGIS network client is unavailable.")
            return
        if self._platform_sync_in_flight:
            self._error("A platform sync or reconciliation request is already in progress.")
            return
        if self._pending_platform_sync_load_error:
            self._error(
                "A saved platform sync record cannot be read safely; no new sync was sent. "
                + self._pending_platform_sync_load_error
            )
            return
        try:
            base_url = platform_api_base_url()
            current_project_id = project_id(QgsProject.instance())
        except ValueError as exc:
            self._error(str(exc))
            return
        if self._pending_platform_sync_operation is not None:
            pending = self._pending_platform_sync_operation
            if pending["project_id"] != current_project_id:
                self._error("A pending platform sync belongs to another project; no request was sent.")
                return
            if pending["api_base_url"] != base_url:
                self._error("The platform API origin changed since the pending sync; no request was sent.")
                return
            self._platform_sync_in_flight = True
            request = QNetworkRequest(QUrl(f"{base_url}/api/v1/workspaces/{pending['workspace_id']}/history"))
            reply = self._network.get(request)
            self._track_reply(reply, lambda item: self._handle_pending_platform_history_reply(item, pending))
            self._message("Checking platform history for the saved sync request before any retry…")
            return
        try:
            selected = self._selected_source_references()
        except ValueError as exc:
            self._error(str(exc))
            return
        if not selected:
            self._error("Select at least one feature with a stable BAG/OSM source ID in the active layer.")
            return
        self._pending_platform_context = (current_project_id, selected)
        request = QNetworkRequest(QUrl(f"{base_url}/api/v1/projects/{current_project_id}/site-context"))
        self._message("Resolving selected feature references against the active StudyArea and spatial-r01 sources…")
        self._platform_sync_in_flight = True
        reply = self._network.get(request)
        self._track_reply(reply, self._handle_platform_context_reply)

    def _selected_source_references(self) -> list[dict[str, str]]:
        layer = self.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            raise ValueError("Select a vector source layer before syncing to the platform")
        selected = list(layer.selectedFeatures())
        if not 1 <= len(selected) <= 100:
            raise ValueError("Select between 1 and 100 source features before syncing")
        refs: list[dict[str, str]] = []
        for feature in selected:
            attrs = {field.name(): feature.attribute(field.name()) for field in layer.fields()}
            refs.append(qgis_source_feature_reference(layer.name(), attrs))
        ids = [item["feature_id"] for item in refs]
        if len(ids) != len(set(ids)):
            raise ValueError("The selection contains duplicate stable source IDs")
        return refs

    def _handle_platform_context_reply(self, reply: Any) -> None:
        self._platform_sync_in_flight = False
        pending = self._pending_platform_context
        self._pending_platform_context = None
        payload, error = self._reply_json(reply)
        if error:
            self._error(f"Platform site-context unavailable: {error}")
            return
        if pending is None:
            self._error("Platform sync references expired; select features and try again.")
            return
        current_project_id, selected_refs = pending
        study_area = payload.get("study_area")
        if (
            payload.get("project_id") != current_project_id
            or payload.get("source_integrity_status") != "VERIFIED"
            or not isinstance(study_area, dict)
            or study_area.get("status") != "CONFIRMED_FOR_EXPLORATION"
        ):
            self._error("Platform sync is blocked: active project, StudyArea, or spatial-r01 source verification did not match.")
            return
        features_by_id = {
            str(feature.get("id")): feature
            for feature in list(payload.get("buildings", [])) + list(payload.get("roads", []))
        }
        selected_features = []
        for ref in selected_refs:
            feature = features_by_id.get(ref["feature_id"])
            if not feature or feature.get("feature_kind") != ref["feature_kind"]:
                self._error(f"Selected source reference {ref['feature_id']!r} is not in the active verified catalog.")
                return
            selected_features.append(feature)
        current_workspace = payload.get("current_workspace")
        try:
            request_body = build_platform_sync_payload(
                project_id=current_project_id,
                study_area_id=str(study_area["id"]),
                expected_workspace_revision=int((current_workspace or {}).get("revision", 0)),
                actor_session_id=self._qgis_instance(),
                source_snapshot_ids=list(payload.get("source_snapshot_ids", [])),
                selected_features=selected_features,
                current_workspace=current_workspace,
            )
            base_url = platform_api_base_url()
            pending_operation = create_pending_platform_sync(base_url, request_body)
        except (KeyError, TypeError, ValueError) as exc:
            self._error(f"Platform sync request is invalid: {exc}")
            return
        try:
            self._save_pending_platform_sync(pending_operation)
        except (RuntimeError, ValueError) as exc:
            self._error(f"Sync was not dispatched because its exact request could not be saved safely: {exc}")
            return
        self._pending_platform_sync_operation = pending_operation
        self._dispatch_pending_platform_sync(pending_operation)

    def _save_pending_platform_sync(self, pending: dict[str, Any]) -> None:
        settings = QSettings()
        settings.setValue(PENDING_PLATFORM_SYNC_SETTINGS_KEY, serialize_pending_platform_sync(pending))
        settings.sync()
        if settings.status() != QSettings.NoError:
            raise RuntimeError("QGIS could not persist the pending sync in its isolated profile")

    def _clear_pending_platform_sync(self) -> None:
        settings = QSettings()
        settings.remove(PENDING_PLATFORM_SYNC_SETTINGS_KEY)
        settings.sync()
        if settings.status() != QSettings.NoError:
            raise RuntimeError("QGIS could not clear the reconciled sync record")
        self._pending_platform_sync_operation = None

    def _dispatch_pending_platform_sync(self, pending: dict[str, Any]) -> None:
        if self._network is None:
            self._platform_sync_in_flight = False
            self._error("The exact sync is saved but the QGIS network client is unavailable; it was not dispatched.")
            return
        request = QNetworkRequest(QUrl(f"{pending['api_base_url']}/api/v1/workspaces/sync"))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        body = QByteArray(
            json.dumps(pending["request_body"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        self._platform_sync_in_flight = True
        reply = self._network.post(request, body)
        self._track_reply(reply, lambda item: self._handle_platform_sync_reply(item, pending))
        self._message("Syncing the saved request as a non-binding DRAFT workspace revision…")

    def _handle_pending_platform_history_reply(self, reply: Any, pending: dict[str, Any]) -> None:
        self._platform_sync_in_flight = False
        history, error = self._reply_json_list(reply)
        if error:
            self._error(f"Platform sync remains OUTCOME_UNKNOWN; history could not be checked: {error}")
            return
        try:
            revision = matching_pending_sync_revision(history, pending)
        except ValueError as exc:
            self._error(f"Platform sync remains OUTCOME_UNKNOWN; history did not reconcile safely: {exc}")
            return
        if revision is not None:
            try:
                revision_number = validate_pending_sync_revision(revision, pending)
                self._clear_pending_platform_sync()
            except (RuntimeError, ValueError) as exc:
                self._error(f"Platform history found the sync, but local reconciliation remains pending: {exc}")
                return
            self._message(
                f"Reconciled the saved platform sync as DRAFT revision {revision_number}; no new revision was created."
            )
            return
        self._message("No matching revision is recorded; replaying the exact saved request with its original key…")
        self._dispatch_pending_platform_sync(pending)

    def _handle_platform_sync_reply(self, reply: Any, pending: dict[str, Any]) -> None:
        self._platform_sync_in_flight = False
        payload, error = self._reply_json(reply)
        if error:
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status_code is not None and 400 <= int(status_code) < 500:
                try:
                    self._clear_pending_platform_sync()
                except RuntimeError as exc:
                    self._error(f"Platform rejected the draft sync ({error}); saved request could not be cleared: {exc}")
                    return
                self._error(f"Platform rejected the draft sync: {error}. No automatic retry was sent.")
            else:
                self._error(
                    "Platform sync outcome is OUTCOME_UNKNOWN after dispatch. "
                    "The exact request is saved; click Sync to Platform to reconcile before any replay."
                )
            return
        revision = payload.get("workspace_revision", {})
        try:
            revision_number = validate_pending_sync_revision(revision, pending)
            self._clear_pending_platform_sync()
        except (TypeError, ValueError, RuntimeError) as exc:
            self._error(
                "Platform response did not confirm the exact persisted DRAFT revision. "
                f"OUTCOME_UNKNOWN is retained for reconciliation: {exc}"
            )
            return
        self._message(f"Platform persisted DRAFT revision {revision_number}; no human decision was inferred.")

    def refresh_status(self) -> None:
        """Fetch integration readiness without blocking QGIS's GUI thread."""
        self._require_qgis()
        if self._network is None:
            return
        anchor_status, context_status, local_detail = self._local_readiness()
        self._update_action_state()
        try:
            base_url = bridge_url()
        except ValueError as exc:
            self._set_status(
                format_status(
                    {}, anchor_status=anchor_status, context_status=context_status
                ).replace("Backend: UNKNOWN", "Backend: REJECTED")
            )
            self._error(str(exc))
            return
        request = QNetworkRequest(QUrl(f"{base_url}/api/v1/integrations/status"))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        token = session_token()
        if token:
            request.setRawHeader(QByteArray(b"X-Urban-Design-Session-Token"), QByteArray(token.encode("utf-8")))
        self._set_status(
            f"Backend: checking… | QGIS MCP: checking… | Ladybug: checking… | "
            f"Anchor: {anchor_status} | Context: {context_status}"
        )
        reply = self._network.get(request)
        self._track_reply(reply, self._handle_status_reply)

    def _post_capture(self, current_project_id: str, payload: dict[str, object], token: str) -> None:
        if self._network is None:
            self._error("The QGIS network client is unavailable.")
            return
        try:
            base_url = bridge_url()
        except ValueError as exc:
            self._error(str(exc))
            return
        url = f"{base_url}/api/v1/projects/{current_project_id}/study-area/capture"
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setRawHeader(QByteArray(b"X-Urban-Design-Session-Token"), QByteArray(token.encode("utf-8")))
        # This is deliberately built from the fixed helper.  It contains only
        # instance, layer_id, fid, actor, and request_id—never geometry, path,
        # target CRS, or a QGIS filter expression.
        body = QByteArray(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        reply = self._network.post(request, body)
        self._track_reply(reply, lambda item: self._handle_capture_reply(item, current_project_id))
        self._message("Study Area capture sent; waiting for backend/QGIS MCP confirmation…")

    def _handle_status_reply(self, reply: Any) -> None:
        payload, error = self._reply_json(reply)
        if error:
            anchor_status, context_status, _detail = self._local_readiness()
            self._set_status(
                f"Backend: OFFLINE | QGIS MCP: UNKNOWN | Ladybug: UNKNOWN | "
                f"Anchor: {anchor_status} | Context: {context_status}"
            )
            self._error(f"Integration status unavailable: {error}")
            return
        anchor_status, context_status, _detail = self._local_readiness()
        self._set_status(format_status(payload, anchor_status=anchor_status, context_status=context_status))

    def _handle_capture_reply(self, reply: Any, current_project_id: str) -> None:
        payload, error = self._reply_json(reply)
        kind = capture_result_kind(payload, error)
        if kind == "unknown":
            self._error(
                "Study Area capture outcome is OUTCOME_UNKNOWN. Reconcile the backend artifact/state before retrying."
            )
            return
        if kind == "error":
            self._error(f"Study Area capture failed for {current_project_id}: {error}")
            return
        status = str(payload.get("status", "")).upper()
        if status not in {"CONFIRMED", "CONFIRMED_FOR_EXPLORATION", "READY", "SUCCESS", "OK"} and payload.get("error"):
            self._error(str(payload["error"]))
            return
        study_area_id = payload.get("study_area_id", payload.get("id", "unknown"))
        version = payload.get("version", payload.get("study_area_version", "unknown"))
        self._message(f"Study Area confirmed for {current_project_id}: {study_area_id} v{version} ({status or 'OK'}).")

    def _get_or_create_draft_layer(self) -> Any | None:
        existing = [
            layer for layer in QgsProject.instance().mapLayers().values() if layer.name() == DRAFT_LAYER_NAME
        ]
        if len(existing) > 1:
            self._error(f"Multiple layers are named {DRAFT_LAYER_NAME}; resolve this ambiguity first.")
            return None
        if existing:
            layer = existing[0]
            if not layer.isValid():
                # The repaired project points at the new sibling path.  QGIS
                # may have created an invalid placeholder before the file
                # existed; remove only that placeholder, never the preserved
                # historical nested GeoPackage.
                source = str(layer.source())
                if source.endswith("study-area-draft.gpkg|layername=Study Area Draft"):
                    QgsProject.instance().removeMapLayer(layer.id())
                    existing = []
                else:
                    self._error("The existing Study Area Draft layer is unresolved; historical files were left untouched.")
                    return None
            if not existing:
                layer = None
            else:
                layer = existing[0]
        if existing:
            if not self._is_dedicated_layer(layer):
                self._error(
                    f"{DRAFT_LAYER_NAME} must be a persistent GeoPackage polygon layer in {DRAFT_CRS_AUTHID}."
                )
                return None
            self.iface.setActiveLayer(layer)
            return layer

        project = QgsProject.instance()
        project_file = project.fileName()
        base = Path(project_file).parent if project_file else Path(project.homePath() or os.getcwd())
        # The project already lives in .urban_design_runtime.  Appending the
        # same directory name here created .urban_design_runtime/.urban_design_runtime.
        # Keep that historical file untouched and place new drafts beside the
        # project file instead.
        runtime_dir = base
        runtime_dir.mkdir(parents=True, exist_ok=True)
        gpkg_path = runtime_dir / "study-area-draft.gpkg"
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = DRAFT_LAYER_NAME
        options.fileEncoding = "UTF-8"
        writer = QgsVectorFileWriter.create(
            str(gpkg_path),
            QgsFields(),
            QgsWkbTypes.Polygon,
            QgsCoordinateReferenceSystem(DRAFT_CRS_AUTHID),
            project.transformContext(),
            options,
        )
        try:
            if writer.hasError() != QgsVectorFileWriter.NoError:
                self._error(f"Could not create persistent Study Area Draft: {writer.errorMessage()}")
                return None
        finally:
            del writer
        layer = QgsVectorLayer(f"{gpkg_path}|layername={DRAFT_LAYER_NAME}", DRAFT_LAYER_NAME, "ogr")
        if not layer.isValid() or not self._is_dedicated_layer(layer):
            self._error("The persistent Study Area Draft layer could not be loaded.")
            return None
        project.addMapLayer(layer)
        return layer

    def _dedicated_layer(self) -> Any | None:
        layer = self.iface.activeLayer()
        if layer is None or layer.name() != DRAFT_LAYER_NAME or not self._is_dedicated_layer(layer):
            self._error(f"Activate the dedicated {DRAFT_LAYER_NAME} polygon layer first.")
            return None
        if layer.type() != QgsMapLayerType.VectorLayer:
            self._error(f"{DRAFT_LAYER_NAME} is not a vector layer.")
            return None
        return layer

    @staticmethod
    def _is_dedicated_layer(layer: Any) -> bool:
        try:
            crs = layer.crs()
            authid = crs.authid().upper()
            provider = layer.providerType().lower()
            source = str(layer.source()).lower()
            return (
                provider in {"ogr", "gpkg"}
                and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry
                and authid == DRAFT_CRS_AUTHID
                and (source.endswith(".gpkg") or ".gpkg|" in source)
            )
        except Exception:
            return False

    @staticmethod
    def _feature_by_fid(layer: Any, fid: int) -> Any | None:
        request = QgsFeatureRequest().setFilterFid(fid)
        iterator = layer.getFeatures(request)
        return next(iter(iterator), None)

    def _qgis_instance(self) -> str:
        try:
            return str(QgsProject.instance().absoluteFilePath() or QgsProject.instance().fileName())
        except Exception:
            return "qgis"

    def _track_reply(self, reply: Any, callback: Any) -> None:
        self._pending_replies.add(reply)

        def finished() -> None:
            self._pending_replies.discard(reply)
            try:
                callback(reply)
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)

    @staticmethod
    def _reply_json(reply: Any) -> tuple[dict[str, Any], str | None]:
        try:
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            raw = bytes(reply.readAll()).decode("utf-8")
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                return {}, "Bridge returned a non-object response"
            if reply.error() != reply.NoError:
                detail = response_error_text(payload, fallback=str(reply.errorString()))
                return payload, f"HTTP {status_code or 'error'}: {detail}"
            if status_code is not None and int(status_code) >= 400:
                return payload, f"HTTP {status_code}: {response_error_text(payload)}"
            return payload, None
        except Exception as exc:
            return {}, str(exc)

    @staticmethod
    def _reply_json_list(reply: Any) -> tuple[list[Any], str | None]:
        """Read the history endpoint's JSON array without treating HTTP errors as history."""
        try:
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            raw = bytes(reply.readAll()).decode("utf-8")
            payload = json.loads(raw) if raw else None
            error_payload = payload if isinstance(payload, dict) else {}
            if reply.error() != reply.NoError:
                detail = response_error_text(error_payload, fallback=str(reply.errorString()))
                return [], f"HTTP {status_code or 'error'}: {detail}"
            if status_code is not None and int(status_code) >= 400:
                return [], f"HTTP {status_code}: {response_error_text(error_payload)}"
            if not isinstance(payload, list):
                return [], "platform workspace history returned a non-list response"
            return payload, None
        except Exception as exc:
            return [], str(exc)

    def _set_status(self, text: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(text)

    def _message(self, text: str) -> None:
        try:
            self.iface.messageBar().pushInfo("Urban Design", text)
        except Exception:
            pass

    def _error(self, text: str) -> None:
        try:
            self.iface.messageBar().pushCritical("Urban Design", text)
        except Exception:
            try:
                QMessageBox.critical(self.iface.mainWindow(), "Urban Design", text)
            except Exception:
                pass

    @staticmethod
    def _require_qgis() -> None:
        if not QGIS_AVAILABLE:
            raise RuntimeError("The Urban Design QGIS plugin must run inside QGIS.")
