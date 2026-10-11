---
name: html-css-artifact-generator
description: Generate secure, visually polished, responsive HTML and CSS artifacts for landing pages, dashboards, announcements, and UI components from natural language descriptions and Lenny's podcast insights.
---

# HTML/CSS Artifact Generation Skill

## Purpose
Enables users to request and generate complete, responsive, and aesthetically modern HTML/CSS design artifacts (landing pages, dashboards, announcements, pricing grids, and component showcases) using the genuine Pi Coding Agent with defensible server-side sanitization.

## Core Capabilities
1. **Dynamic Prompting**: Translates user requirements and optional Lenny's Podcast transcript evidence into clean HTML5 and CSS3.
2. **Strict Server-Side Sanitization**:
   - Strips `<script>`, `<iframe>`, `<object>`, `<embed>`, `<form>`, and active container elements.
   - Completely suppresses untrusted `<svg>` and `<math>` elements and all their descendants.
   - Eliminates all inline JavaScript event handlers (`on*`).
   - Rejects executable URL schemes (`javascript:`, `vbscript:`, SVG data URIs).
   - Blocks external network resource loading (no remote images, remote fonts, or external media).
   - Sanitizes CSS against remote `@import`, executable expressions (`expression(...)`), and external network resource leaks (`url(http...)`).
3. **Responsive Visual Quality**:
   - Flexbox and CSS Grid layout structures.
   - Mobile `@media` query breakpoints.
   - Modern system font stacks and accessible contrast ratios.
4. **Sandboxed Preview Assembly**:
   - Generates an isolated `<!DOCTYPE html>` preview document with an ultra-strict `Content-Security-Policy` (`default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; ...`).
5. **PostgreSQL Persistence**:
   - Automatically stores artifacts in session history under `chat_messages` with structured metadata for reliable retrieval across browser sessions.
