# Apartment Finder - Docker Deployment Guide

This guide explains how to build and run the Apartment Finder application using Docker and Docker Compose with Nginx reverse proxy and SSL/TLS support.

## Prerequisites

- Docker (version 20.10+)
- Docker Compose (version 1.29+)
- SSL certificates in `../!gateway/nginx/certs/` directory:
  - `fullchain.pem` - The SSL certificate chain
  - `privkey.pem` - The private key

## Project Structure

```
appartment_finder/
├── Dockerfile              # Flask app container definition
├── docker-compose.yml      # Docker Compose orchestration
├── nginx.conf             # Nginx server configuration
├── .env.example           # Example environment variables
├── requirements.txt       # Python dependencies
├── run.py                # Flask application entry point
├── app/                  # Application source code
├── instance/             # Instance-specific files (created at runtime)
└── migrations/           # Database migrations
```

## SSL Certificates

The nginx container expects SSL certificates in: `../!gateway/nginx/certs/`

Required files:
- `fullchain.pem` - Full certificate chain
- `privkey.pem` - Private key

If you don't have certificates yet, you can generate self-signed certificates for testing:

```bash
mkdir -p ../!gateway/nginx/certs
openssl req -x509 -newkey rsa:4096 -keyout ../!gateway/nginx/certs/privkey.pem \
  -out ../!gateway/nginx/certs/fullchain.pem -days 365 -nodes
```

For production, use Let's Encrypt or your certificate provider.

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and update values as needed:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```
SECRET_KEY=your-production-secret-key
MAIN_DATABASE_URL=postgresql://user:password@db-host:5432/apartment_finder
PLANNING_DATABASE_URL=postgresql://user:password@db-host:5432/planning_db
MAIL_SERVER=your-mail-server
MAIL_SERVER_PORT=587
SEND_FROM_EMAIL=your-email@example.com
SEND_FROM_EMAIL_PASSWORD=your-password
```

### Database Configuration

The application supports multiple databases:

- **Main Database**: SQLite (default) or PostgreSQL
- **Planning Database**: SQLite (default) or PostgreSQL  
- **MySQL Source**: For data import (connection string in config.py)

For production, configure PostgreSQL databases.

## Building and Running

### Build the Docker Image

```bash
docker-compose build
```

### Start Services

```bash
# Start in detached mode (background)
docker-compose up -d

# Or run in foreground to see logs
docker-compose up
```

### Check Service Status

```bash
docker-compose ps
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app
docker-compose logs -f nginx
```

## Accessing the Application

- **HTTPS (Secure)**: https://localhost (port 443)
- **HTTP**: http://localhost (redirects to HTTPS)

**Note**: If using self-signed certificates, your browser will show a security warning. Accept the risk to proceed.

## API Endpoints

The application is exposed through nginx proxy. All routes go through:
- `https://localhost/` (default)

The nginx configuration proxies all requests to the Flask app running on port 5000 internally.

## Database Management

### Initialize Database

The `run.py` script automatically initializes the database with:
- Table creation
- Default roles (MPP, MANAGER, ADMIN, etc.)
- Admin user account

First run will set up everything automatically.

### Run Migrations

For database migrations, use Flask-Migrate:

```bash
# Inside the container
docker-compose exec app flask db upgrade
docker-compose exec app flask db migrate -m "Migration message"
```

### Access Database

#### SQLite:
```bash
docker-compose exec app sqlite3 instance/main_app.db
```

#### PostgreSQL:
```bash
docker-compose exec app psql postgresql://user:password@db-host/database
```

## Stopping Services

```bash
# Stop all services (containers still exist)
docker-compose stop

# Stop and remove containers
docker-compose down

# Stop and remove containers + volumes
docker-compose down -v
```

## Troubleshooting

### Certificate Issues

If nginx won't start with certificate errors:

```bash
# Check certificate files exist
ls -la ../!gateway/nginx/certs/

# Verify certificate
openssl x509 -in ../!gateway/nginx/certs/fullchain.pem -text -noout

# Check nginx configuration
docker-compose exec nginx nginx -t
```

### Port Already in Use

If port 443 is already in use:

```bash
# Check what's using the port
sudo lsof -i :443

# Change port in docker-compose.yml
# Change: "443:443" to "8443:443"
```

### Flask App Not Starting

Check the logs:
```bash
docker-compose logs app
```

Common issues:
- Database connection failures
- Missing environment variables
- Port 5000 already in use inside container

### Nginx Connection Refused

Ensure the app service is healthy:
```bash
docker-compose ps
# Look for "healthy" status on app service
```

## Performance Optimization

### For Production

1. **Set environment**: Change `FLASK_ENV=production` in `.env`
2. **Use Gunicorn**: Modify Dockerfile to use Gunicorn instead of Flask dev server
3. **Enable caching**: Configure Redis or Memcached
4. **Database**: Use PostgreSQL instead of SQLite
5. **SSL**: Use proper certificates from Let's Encrypt
6. **Logging**: Configure proper log rotation

### Updated Dockerfile for Production

```dockerfile
# Add to Dockerfile
RUN pip install gunicorn

# Change CMD to:
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "run:app"]
```

## Security Considerations

1. **Change Default Values**: 
   - Update `SECRET_KEY` in `.env`
   - Change admin credentials after first login
   - Update email passwords

2. **Restrict Access**:
   - Configure firewall rules
   - Use nginx authentication if needed
   - Enable CORS properly in Flask app

3. **Secrets Management**:
   - Use Docker secrets in production
   - Don't commit `.env` file to git
   - Rotate certificates regularly

4. **Network Security**:
   - Use internal docker network (default)
   - Don't expose database ports
   - Enable SSL/TLS only mode in nginx

## Monitoring

### Container Resource Usage

```bash
docker stats
```

### Application Health

```bash
curl -k https://localhost/
```

### Log Rotation

Configure Docker to limit log file sizes in `docker-compose.yml`:

```yaml
services:
  app:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## Backup and Recovery

### Backup Data

```bash
# Backup SQLite databases
docker-compose exec app tar czf - instance/ > backup.tar.gz

# Backup volumes
docker run --rm -v apartmentfinder_app_data:/app_data -v $(pwd):/backup \
  alpine tar czf /backup/app_data.tar.gz /app_data
```

### Restore Data

```bash
# Restore SQLite databases
docker-compose exec app tar xzf /backup.tar.gz

# Restore volumes
docker run --rm -v apartmentfinder_app_data:/app_data -v $(pwd):/backup \
  alpine tar xzf /backup/app_data.tar.gz -C /
```

## Development vs Production

### Development
- Debug mode: enabled
- SQLite database: sufficient
- Self-signed certificates: acceptable
- Hot reload: available

### Production
- Debug mode: disabled
- PostgreSQL: recommended
- Valid SSL certificates: required
- Use Gunicorn or similar WSGI server
- Implement proper logging and monitoring

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Nginx Documentation](https://nginx.org/en/docs/)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Let's Encrypt](https://letsencrypt.org/) - Free SSL certificates

## Support

For issues or questions, check:
1. Docker Compose logs: `docker-compose logs`
2. Application logs in `instance/` directory
3. Nginx error logs: `docker-compose logs nginx`
