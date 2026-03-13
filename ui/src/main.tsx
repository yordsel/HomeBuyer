import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { GlobalErrorBoundary } from './components/GlobalErrorBoundary';
import './index.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <GlobalErrorBoundary>
      <App />
    </GlobalErrorBoundary>
  </React.StrictMode>,
);
