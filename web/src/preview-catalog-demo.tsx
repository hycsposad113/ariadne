import { createRoot } from 'react-dom/client';
import { MorphologyPreviewCatalog } from './components/MorphologyPreviewCatalog';

const apiBase = new URLSearchParams(window.location.search).get('api') ?? window.location.origin;
const root = document.getElementById('preview-root');

if (!root) {
  throw new Error('Missing isolated preview mount element.');
}

createRoot(root).render(<MorphologyPreviewCatalog apiBase={apiBase} />);
