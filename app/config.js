// config.js – makes REACT_APP_ENDPOINT available in the browser
// Adjust the value here or generate it from a .env file during deployment.
window.REACT_APP_ENDPOINT =
  window.REACT_APP_ENDPOINT ||
  'http://localhost:8000/api/v1/auth/password-reset';
