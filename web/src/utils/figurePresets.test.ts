import { describe, expect, it } from 'vitest';
import {
  buildIsometricCameraPreset,
  buildPerspectiveCameraPreset,
  buildPlanCameraPreset,
  calculateOrthographicFraming,
  createFigureMetadataStamp,
  STANDARD_RESOLUTIONS,
  TRUE_ISOMETRIC_AZIMUTH_DEG,
  TRUE_ISOMETRIC_ELEVATION_DEG,
  type BoundingBox3D,
} from './figurePresets';

describe('figurePresets (W6 precursor lane F4)', () => {
  const sampleBBox: BoundingBox3D = {
    minX: 100,
    minY: 200,
    minZ: 0,
    maxX: 500,
    maxY: 600,
    maxZ: 50,
  };

  it('calculates true isometric camera angles and parameters', () => {
    const res = STANDARD_RESOLUTIONS.FHD_1080P;
    const camera = buildIsometricCameraPreset(sampleBBox, res);

    expect(camera.cameraType).toBe('orthographic');
    expect(camera.azimuthDeg).toBe(TRUE_ISOMETRIC_AZIMUTH_DEG);
    expect(camera.elevationDeg).toBeCloseTo(35.264, 3);
    expect(TRUE_ISOMETRIC_ELEVATION_DEG).toBeCloseTo(35.264, 3);

    // Camera target is center of bounding box
    expect(camera.target).toEqual([300, 400, 25]);

    // Direction vector from target to camera has equal projections in magnitude (1 / sqrt(3))
    const dx = camera.position[0] - camera.target[0];
    const dy = camera.position[1] - camera.target[1];
    const dz = camera.position[2] - camera.target[2];
    expect(Math.abs(dx)).toBeCloseTo(Math.abs(dy), 1);
    expect(Math.abs(dx)).toBeCloseTo(Math.abs(dz), 1);
  });

  it('calculates plan camera preset with top-down orientation', () => {
    const res = STANDARD_RESOLUTIONS.FHD_1080P;
    const camera = buildPlanCameraPreset(sampleBBox, res);

    expect(camera.cameraType).toBe('orthographic');
    expect(camera.elevationDeg).toBe(90.0);
    expect(camera.up).toEqual([0, 1, 0]); // North is +Y
    expect(camera.target).toEqual([300, 400, 25]);
    expect(camera.position[0]).toBe(300);
    expect(camera.position[1]).toBe(400);
    expect(camera.position[2]).toBeGreaterThan(25);
  });

  it('perspective preset strictly disallows a 2D scale bar', () => {
    const res = STANDARD_RESOLUTIONS.FHD_1080P;
    const directCam = buildPerspectiveCameraPreset(sampleBBox, res, 50.0);
    expect(directCam.cameraType).toBe('perspective');
    expect(directCam.fov).toBe(50.0);
    expect(directCam.aspect).toBe(res.width / res.height);

    const stamp = createFigureMetadataStamp({
      presetKind: 'PERSPECTIVE',
      bbox: sampleBBox,
      proposalRevision: 'rev-3',
      gitCommit: 'abc1234',
      status: 'ILLUSTRATIVE',
    });

    expect(stamp.presetKind).toBe('PERSPECTIVE');
    expect(stamp.camera.cameraType).toBe('perspective');
    // Acceptance criterion: 透視預設不產生比例尺
    expect(stamp.scaleBar).toBeNull();
    expect(stamp.northArrow).toBeNull();
  });

  it('plan and isometric presets include valid metric scale bars', () => {
    const planStamp = createFigureMetadataStamp({
      presetKind: 'PLAN',
      bbox: sampleBBox,
      proposalRevision: 1,
      gitCommit: 'def5678',
      status: 'DRAFT',
    });
    expect(planStamp.scaleBar).not.toBeNull();
    expect(planStamp.scaleBar?.unit).toBe('m');
    expect(planStamp.scaleBar?.distanceMeters).toBeGreaterThan(0);
    expect(planStamp.northArrow?.enabled).toBe(true);

    const isoStamp = createFigureMetadataStamp({
      presetKind: 'ISOMETRIC',
      bbox: sampleBBox,
      proposalRevision: 2,
      gitCommit: 'def5678',
      status: 'REVIEWED',
    });
    expect(isoStamp.scaleBar).not.toBeNull();
    expect(isoStamp.scaleBar?.unit).toBe('m');
  });

  it('two proposals sharing the same bounding box produce strictly identical scale and framing', () => {
    // Acceptance criterion: 兩個方案共用取景時比例相同
    const res = STANDARD_RESOLUTIONS.FHD_1080P;
    const framingA = calculateOrthographicFraming(sampleBBox, res);
    const framingB = calculateOrthographicFraming(sampleBBox, res);

    expect(framingA.pixelsPerMeter).toBe(framingB.pixelsPerMeter);
    expect(framingA.frustumWidth).toBe(framingB.frustumWidth);
    expect(framingA.frustumHeight).toBe(framingB.frustumHeight);
    expect(framingA.center).toEqual(framingB.center);

    const stampA = createFigureMetadataStamp({
      presetKind: 'ISOMETRIC',
      bbox: sampleBBox,
      resolution: res,
      proposalRevision: 'option-A',
      gitCommit: 'commit1',
      status: 'DRAFT',
    });
    const stampB = createFigureMetadataStamp({
      presetKind: 'ISOMETRIC',
      bbox: sampleBBox,
      resolution: res,
      proposalRevision: 'option-B',
      gitCommit: 'commit2',
      status: 'STALE',
    });

    const camA = stampA.camera as ReturnType<typeof buildIsometricCameraPreset>;
    const camB = stampB.camera as ReturnType<typeof buildIsometricCameraPreset>;

    expect(camA.pixelsPerMeter).toBe(camB.pixelsPerMeter);
    expect(camA.frustum).toEqual(camB.frustum);
    expect(camA.position).toEqual(camB.position);
    expect(camA.target).toEqual(camB.target);
  });

  it('retains visible status markers for DRAFT, STALE, and ILLUSTRATIVE', () => {
    for (const status of ['DRAFT', 'STALE', 'ILLUSTRATIVE'] as const) {
      const stamp = createFigureMetadataStamp({
        presetKind: 'PLAN',
        bbox: sampleBBox,
        proposalRevision: 4,
        gitCommit: 'hash999',
        status,
      });
      expect(stamp.status).toBe(status);
    }
  });
});
