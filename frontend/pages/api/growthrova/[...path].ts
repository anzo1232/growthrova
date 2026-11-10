import type { NextApiRequest, NextApiResponse } from "next";
import http from "node:http";
import https from "node:https";

export const config = { api: { bodyParser: false, responseLimit: false } };

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader("Cache-Control", "no-store");
  const token = req.headers.authorization;
  if (!token?.startsWith("Bearer ")) {
    return res.status(401).json({ error: "Sign in to your Growthrova account." });
  }
  const segments = req.query.path;
  if (!Array.isArray(segments) || segments.some(part => !/^[a-zA-Z0-9_.-]+$/.test(part) || part === "." || part === "..")) {
    return res.status(400).json({ error: "Invalid workspace request." });
  }
  const origin = process.env.GROWTHROVA_BACKEND_ORIGIN;
  if (!origin) return res.status(503).json({ error: "The workspace connection is unavailable. Please try again shortly." });
  const target = new URL(origin);
  target.pathname = "/api/growthrova/" + segments.map(encodeURIComponent).join("/");
  target.search = new URL(req.url || "/", "http://localhost").search;
  const headers: Record<string, string> = { authorization: token, accept: req.headers.accept || "application/json" };
  for (const name of ["content-type", "content-length"]) {
    const value = req.headers[name];
    if (typeof value === "string") headers[name] = value;
  }
  return new Promise<void>(resolve => {
    const transport = target.protocol === "https:" ? https : http;
    const upstream = transport.request(target, { method: req.method, headers }, response => {
      res.statusCode = response.statusCode || 502;
      for (const name of ["content-type", "content-disposition"]) {
        const value = response.headers[name];
        if (value) res.setHeader(name, value);
      }
      response.on("error", () => { res.destroy(); resolve(); });
      response.on("end", resolve);
      response.pipe(res);
    });
    upstream.setTimeout(180000, () => upstream.destroy(new Error("timeout")));
    upstream.on("error", () => {
      if (!res.headersSent) res.status(502).json({ error: "The workspace connection was interrupted. Reopen the saved request before trying again." });
      else res.destroy();
      resolve();
    });
    req.on("aborted", () => upstream.destroy());
    res.on("close", () => { if (!res.writableEnded) upstream.destroy(); });
    req.pipe(upstream);
  });
}
