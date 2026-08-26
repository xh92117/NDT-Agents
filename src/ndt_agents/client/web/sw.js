"use strict";

const CACHE_NAME = "ndt-workbench-shell-v1";
const SHELL = [
  "/workbench",
  "/workbench/assets/workbench.css",
  "/workbench/assets/workbench.js",
  "/workbench/assets/manifest.webmanifest",
  "/workbench/assets/icon.svg"
];

function isPublicShellRequest(request) {
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return false;
  if (request.headers.has("authorization") || url.pathname.startsWith("/v1/")) return false;
  return url.pathname === "/workbench" || url.pathname.startsWith("/workbench/assets/");
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) => Promise.all(
      names.filter((name) => name.startsWith("ndt-workbench-shell-") && name !== CACHE_NAME)
        .map((name) => caches.delete(name))
    ))
  );
});

self.addEventListener("fetch", (event) => {
  if (!isPublicShellRequest(event.request)) return;
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
      }
      return response;
    }).catch(() => caches.match(event.request).then((cached) => cached || Response.error()))
  );
});
