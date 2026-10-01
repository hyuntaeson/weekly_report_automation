#!/usr/bin/env python3
"""
Chrome Browser Activity Server
Lightweight HTTP server using Python standard library http.server
Receives page visit events from Chrome extension and saves to database
"""

import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from weekly_report import paths
from weekly_report.storage.database import ActivityDatabase


class ActivityRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for /activity endpoint"""

    # Class variable to store database path
    db_path = paths.DB_PATH

    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        """Handle POST requests to /activity endpoint"""
        if self.path != "/activity":
            self.send_error(404, "Not Found")
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_error(400, "Empty request body")
                return

            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            # Validate required fields
            if not data.get("url") or not data.get("title"):
                self.send_error(400, "Missing required fields: url, title")
                return

            # Create activity record
            activity = {
                "timestamp": data.get("timestamp", datetime.now().isoformat()),
                "action": "page_visited",
                "file_path": data["url"],
                "file_type": "browser_history",
                "source": "browser",
                "details": json.dumps({"title": data["title"]}, ensure_ascii=False),
            }

            # Save to database
            try:
                db = ActivityDatabase(self.db_path)
                db.add_activity(activity)
                db.close()

                # Send success response
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                response = json.dumps(
                    {"status": "success", "message": "Activity recorded"}
                )
                self.wfile.write(response.encode("utf-8"))

            except Exception as db_error:
                print(f"Database error: {db_error}")
                self.send_error(500, f"Database error: {str(db_error)}")

        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
        except Exception as e:
            print(f"Request handler error: {e}")
            self.send_error(500, f"Server error: {str(e)}")

    def log_message(self, format, *args):
        """Override to customize logging"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")


class BrowserActivityServer:
    """Lightweight HTTP server for browser activity collection"""

    def __init__(self, db_path=paths.DB_PATH, host="127.0.0.1", port=5757):
        """
        Initialize the server

        Args:
            db_path: Path to activities database
            host: Server host (default: 127.0.0.1)
            port: Server port (default: 5757)
        """
        self.db_path = db_path
        self.host = host
        self.port = port
        self.server = None
        self.server_thread = None
        self.is_running = False

    def start(self):
        """Start the HTTP server in a background thread"""
        if self.is_running:
            print(f"Server is already running on {self.host}:{self.port}")
            return False

        try:
            # Set database path on handler class
            ActivityRequestHandler.db_path = self.db_path

            # Create and configure server
            self.server = HTTPServer((self.host, self.port), ActivityRequestHandler)
            self.is_running = True

            # Start server in background thread
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()

            print(f"Browser Activity Server started on http://{self.host}:{self.port}")
            print(f"Endpoint: POST http://{self.host}:{self.port}/activity")
            print(f"Database: {self.db_path}")
            return True

        except OSError as e:
            print(f"Failed to start server: {e}")
            self.is_running = False
            return False

    def _run_server(self):
        """Run the server (called in background thread)"""
        try:
            self.server.serve_forever()
        except Exception as e:
            print(f"Server error: {e}")
        finally:
            self.is_running = False

    def stop(self):
        """Stop the HTTP server"""
        if not self.is_running or self.server is None:
            return

        try:
            self.server.shutdown()
            self.server.server_close()

            # Wait for thread to finish
            if self.server_thread:
                self.server_thread.join(timeout=5)

            self.is_running = False
            print("Browser Activity Server stopped")
        except Exception as e:
            print(f"Error stopping server: {e}")

    def is_active(self):
        """Check if server is running"""
        return self.is_running


def main():
    """Test the server"""
    server = BrowserActivityServer(
        db_path=paths.DB_PATH, host="127.0.0.1", port=5757
    )

    try:
        if not server.start():
            print("Failed to start server")
            return

        print("\nServer is running. Press Ctrl+C to stop.")
        print("\nTo test, send a POST request like:")
        print("curl -X POST http://127.0.0.1:5757/activity \\")
        print('  -H "Content-Type: application/json" \\')
        print(
            '  -d \'{"url": "https://example.com", "title": "Example", "timestamp": "2024-09-21T12:00:00"}\''
        )

        # Keep server running
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()


if __name__ == "__main__":
    main()
