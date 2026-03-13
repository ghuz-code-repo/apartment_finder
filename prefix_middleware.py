class PrefixMiddleware:
    """
    Middleware for handling URL prefixes when the app is behind a reverse proxy.
    Sets SCRIPT_NAME so Flask's url_for() generates correct prefixed URLs.
    """
    def __init__(self, wsgi_app, app=None, prefix='/finder'):
        self.wsgi_app = wsgi_app
        self.app = app
        self.prefix = prefix.rstrip('/')

        if app is not None:
            app.config['APPLICATION_ROOT'] = self.prefix
            app.static_url_path = self.prefix + '/static'

    def __call__(self, environ, start_response):
        script_name = environ.get('SCRIPT_NAME', '')
        path_info = environ.get('PATH_INFO', '')

        # Use X-Forwarded-Prefix header set by nginx
        forwarded_prefix = environ.get('HTTP_X_FORWARDED_PREFIX', '').rstrip('/')

        # Static files — nginx already stripped the prefix, no adjustment needed
        if path_info.startswith('/static'):
            return self.wsgi_app(environ, start_response)

        if forwarded_prefix:
            environ['SCRIPT_NAME'] = script_name + forwarded_prefix
            # PATH_INFO stays as is (already stripped by nginx proxy_pass trailing /)
        elif path_info.startswith(self.prefix):
            environ['SCRIPT_NAME'] = script_name + self.prefix
            environ['PATH_INFO'] = path_info[len(self.prefix):] or '/'

        return self.wsgi_app(environ, start_response)
