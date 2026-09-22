// Serve the actual production bundle and one inert hostile-origin page.
import http from "node:http";
import path from "node:path";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const [root, trustedPort, hostilePort] = process.argv.slice(2);
const { default: worker } = await import(pathToFileURL(path.join(root, "dist/server/index.js")));
const mime = { ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".ico": "image/x-icon" };
async function asset(request) {
  const pathname = decodeURIComponent(new URL(request.url).pathname);
  const file = path.resolve(root, "dist/client", "." + pathname);
  if (!file.startsWith(path.join(root, "dist/client") + path.sep)) return new Response("Not found", { status: 404 });
  try { return new Response(await readFile(file), { headers: { "Content-Type": mime[path.extname(file)] || "application/octet-stream" } }); }
  catch { return new Response("Not found", { status: 404 }); }
}

function serve(port, hostile) {
  const server = http.createServer(async (req, res) => {
    try {
      if (/^https?:\/\//i.test(req.url)) {
        console.log("Blocked external browser proxy request", req.url);
        res.writeHead(403); res.end("External browser network disabled"); return;
      }
      if (hostile || req.url === "/__fixture/blank") {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end("<!doctype html><title>Fictional untrusted origin</title><p>Local browser fixture</p>");
        return;
      }
      const request = new Request(`http://127.0.0.1:${port}${req.url}`, { headers: req.headers });
      let response = await asset(request);
      if (response.status === 404) response = await worker.fetch(request, { ASSETS: { fetch: asset } }, { waitUntil() {}, passThroughOnException() {} });
      res.writeHead(response.status, Object.fromEntries(response.headers));
      res.end(Buffer.from(await response.arrayBuffer()));
    } catch (error) { console.error(error); res.writeHead(500); res.end("Fixture UI failure"); }
  });
  server.on("connect", (req, socket) => {
    console.log("Blocked external browser proxy CONNECT", req.url);
    socket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
  });
  server.listen(Number(port), "127.0.0.1");
  return server;
}
const servers = [serve(trustedPort, false), serve(hostilePort, true)];
function stop() { for (const server of servers) server.close(); setTimeout(() => process.exit(0), 500).unref(); }
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
