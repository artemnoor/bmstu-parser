(function attachBmstuApiClient(global) {
  function normalizeBase(value) {
    const raw = String(value || '').trim();
    return (raw || window.location.origin).replace(/\/$/, '');
  }

  class ApiError extends Error {
    constructor(message, status, payload) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.payload = payload;
    }
  }

  function create(getBaseUrl) {
    async function request(path, options = {}) {
      const base = normalizeBase(typeof getBaseUrl === 'function' ? getBaseUrl() : getBaseUrl);
      const target = /^https?:\/\//i.test(path) ? path : `${base}${path.startsWith('/') ? '' : '/'}${path}`;
      const headers = new Headers(options.headers || {});
      headers.set('Accept', 'application/json');

      let body = options.body;
      if (body !== undefined && body !== null && typeof body !== 'string' && !(body instanceof FormData)) {
        body = JSON.stringify(body);
        headers.set('Content-Type', 'application/json');
      }
      if (options.apiKey) headers.set('X-API-Key', options.apiKey);

      const response = await fetch(target, {
        method: options.method || 'GET',
        headers,
        body,
        credentials: options.credentials || 'omit'
      });
      const contentType = response.headers.get('content-type') || '';
      const payload = contentType.includes('json') ? await response.json() : await response.text();
      if (!response.ok) {
        const detail = payload && typeof payload === 'object' ? payload.detail || payload.error : payload;
        throw new ApiError(detail || `API request failed (${response.status})`, response.status, payload);
      }
      return payload;
    }

    return {
      request,
      get: (path, options) => request(path, options),
      post: (path, body, options = {}) => request(path, { ...options, method: 'POST', body })
    };
  }

  global.BmstuApiClient = { ApiError, create };
})(window);
