"""Testler için deterministik, OpenAI-uyumlu sahte model sunucusu.

Gerçek model olmadan uç noktaları test etmeyi sağlar. Her istek için
`FakeLLM.responder(messages, stream) -> str` çağrılır; dönen metin
stream=True ise küçük parçalara bölünüp SSE olarak gönderilir.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLLM:
    def __init__(self):
        self.calls: list[dict] = []
        self.responder = lambda messages, stream: ""
        self.status = 200
        self._server = None

    # ---- yaşam döngüsü
    def start(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.endswith("/models"):
                    body = json.dumps({"object": "list", "data": [{"id": "fake-model"}, {"id": "fake-model-2"}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                fake.calls.append(payload)
                if fake.status != 200:
                    body = b'{"error":"fake failure"}'
                    self.send_response(fake.status)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                text = fake.responder(payload.get("messages", []), bool(payload.get("stream")))
                if payload.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for i in range(0, len(text), 7):
                        chunk = {"choices": [{"delta": {"content": text[i:i + 7]}}]}
                        self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    body = json.dumps({"choices": [{"message": {"content": text}}]}, ensure_ascii=False).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def stop(self):
        if self._server:
            self._server.shutdown()

    # ---- yardımcılar
    def last_user_text(self) -> str:
        msgs = self.calls[-1].get("messages", []) if self.calls else []
        return next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
