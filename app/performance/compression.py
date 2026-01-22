from flask_compress import Compress


def configure_compression(app):
    """
    Configure response compression for improved performance.
    Uses Brotli/GZIP compression for text-based responses.
    """
    # Compression settings
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html',
        'text/css',
        'text/xml',
        'application/json',
        'application/javascript',
        'application/xml',
        'application/xhtml+xml',
        'application/rss+xml'
    ]
    app.config['COMPRESS_LEVEL'] = 9  # Maximum compression level
    app.config['COMPRESS_MIN_SIZE'] = 500  # Minimum response size to compress
    app.config['COMPRESS_BR'] = True  # Enable Brotli compression
    app.config['COMPRESS_GZIP'] = True  # Enable GZIP compression
    
    # Add compression middleware
    Compress(app)
    
    return app
