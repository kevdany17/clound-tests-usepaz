// app.js - Real front‑end for password‑reset request and JSON preview
// Uses React 18 CDN (UMD) – no build tools.

const { useState } = React;

function PasswordResetForm() {
  const defaultEndpoint = 'http://localhost:8000/api/v1/auth/password-reset';
  let envEndpoint = null;
  if (typeof process !== 'undefined' && process.env && process.env.REACT_APP_ENDPOINT) {
    envEndpoint = process.env.REACT_APP_ENDPOINT;
  } else if (typeof window !== 'undefined' && window.REACT_APP_ENDPOINT) {
    envEndpoint = window.REACT_APP_ENDPOINT;
  }
  const [endpoint, setEndpoint] = useState(envEndpoint || defaultEndpoint);
  const [email, setEmail] = useState('');
  const [response, setResponse] = useState(null);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setResponse(null);
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          // NOTE: browsers do NOT allow setting the Host header directly.
          // To test Host‑header poisoning, use a tool like Postman or curl.
        },
        body: JSON.stringify({ email }),
      });
      const json = await res.json();
      setResponse(json);
    } catch (err) {
      setError(err.message);
    }
  };

  return React.createElement(
    'section',
    { className: 'section' },
    React.createElement('h2', null, '1️⃣ Solicitud de restablecimiento de contraseña'),
    React.createElement(
      'form',
      { onSubmit: handleSubmit },
      // React.createElement('label', null, 'Endpoint (POST):'),
      // React.createElement('input', {
      //   type: 'text',
      //   value: endpoint,
      //   onChange: (e) => setEndpoint(e.target.value),
      //   placeholder: 'http://localhost:8000/api/v1/auth/password-reset',
      // }),
      React.createElement('label', null, 'Correo del usuario'),
      React.createElement('input', {
        type: 'email',
        value: email,
        onChange: (e) => setEmail(e.target.value),
        placeholder: 'usuario@ejemplo.com',
        required: true,
      }),
      React.createElement('button', { type: 'submit' }, 'Enviar petición')
    ),
    error && React.createElement('p', { style: { color: '#ff6b6b' } }, `Error: ${error}`),
    response &&
      React.createElement(
        'div',
        { className: 'result' },
        React.createElement('h3', null, 'Respuesta del servidor'),
        React.createElement('pre', null, JSON.stringify(response, null, 2))
      )
  );
}

function JsonPreview() {
  const [rawJson, setRawJson] = useState('');
  const [parsed, setParsed] = useState(null);
  const [parseError, setParseError] = useState(null);

  const handleParse = () => {
    try {
      const obj = JSON.parse(rawJson);
      setParsed(obj);
      setParseError(null);
    } catch (e) {
      setParseError(e.message);
      setParsed(null);
    }
  };

  const renderEmailPreview = (data) => {
    if (!data) return null;
    // Expected shape: { email_preview: { action_url: 'https://...' } }
    const url = data?.email_preview?.action_url;
    if (!url) return React.createElement('p', null, 'No se encontró "action_url" en la respuesta.');
    // Rich institutional email mockup
    return React.createElement(
      'div',
      { className: 'email-mockup' },
      // Header with logo and title
      React.createElement('div', { className: 'email-header' },
        React.createElement('img', { src: 'https://via.placeholder.com/120x40?text=Logo', alt: 'Logo', style: { marginBottom: '1rem' } }),
        React.createElement('h3', null, 'Restablecimiento de Contraseña')
      ),
      // Body with greeting, message and CTA button
      React.createElement('div', { className: 'email-body' },
        React.createElement('p', null, 'Hola,'),
        React.createElement('p', null, 'Hemos recibido una solicitud para restablecer la contraseña de su cuenta. Haga clic en el botón de abajo para confirmar y crear una nueva contraseña.'),
        React.createElement('a', {
          href: url,
          target: '_blank',
          rel: 'noopener',
          className: 'cta-button'
        }, 'Restablecer mi contraseña')
      ),
      // Footer with company info
      React.createElement('div', { className: 'email-footer' },
        React.createElement('p', null, '© 2026 Tu Empresa. Todos los derechos reservados.'),
        React.createElement('p', null, 'Esta es una notificación automática, por favor no responda a este correo.')
      )
    );
  };

  return React.createElement(
    'section',
    { className: 'section' },
    React.createElement('h2', null, '2️⃣ Introduce el JSON devuelto y visualiza el correo'),
    React.createElement('textarea', {
      rows: 8,
      placeholder: 'Pega aquí la respuesta JSON del endpoint...',
      value: rawJson,
      onChange: (e) => setRawJson(e.target.value),
    }),
    React.createElement('button', { onClick: handleParse }, 'Parsear JSON'),
    parseError && React.createElement('p', { style: { color: '#ff6b6b' } }, `Error de parseo: ${parseError}`),
    parsed &&
      React.createElement(
        'div',
        { className: 'result' },
        React.createElement('h3', null, 'JSON parseado'),
        React.createElement('pre', null, JSON.stringify(parsed, null, 2)),
        renderEmailPreview(parsed)
      )
  );
}

function App() {
  return React.createElement(
    'div',
    null,
    React.createElement('h1', null, 'Simulador de Restablecimiento de Contraseña'),
    React.createElement(PasswordResetForm, null),
    React.createElement(JsonPreview, null),
    React.createElement(
      'p',
      { style: { fontSize: '0.85rem', opacity: 0.7, marginTop: '2rem' } },
      'El formulario envía una petición POST al endpoint indicado. Para probar manipulación de encabezados (p.ej., Host), usa Postman o curl, ya que los navegadores no permiten sobrescribir el encabezado Host directamente.'
    )
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
