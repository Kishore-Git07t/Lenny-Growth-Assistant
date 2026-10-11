"""Defensible server-side HTML and CSS sanitization for AI-generated artifacts.

This module enforces a strict, defense-in-depth security boundary on untrusted LLM output.
It guarantees safe static previews by enforcing:
1. Complete removal of active scripting (<script>, inline on* handlers, javascript: URLs).
2. Complete suppression of untrusted SVG and MathML markup and all their descendants.
3. Strict prohibition of external network resource loading (no remote images, fonts,
   media, stylesheets, or CSS @import / remote url() requests).
4. Strict raster-only, size-limited data URIs for embedded imagery (SVG data URIs prohibited).
5. Removal of frames, objects, embeds, and forms.
6. Generation of preview documents containing an ultra-strict Content-Security-Policy.
"""

from html import escape, unescape
from html.parser import HTMLParser
import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import unquote

# Maximum allowed character length for a base64 raster image data URI (50 KB limit)
MAX_IMAGE_DATA_URI_CHARS = 50_000

# Tags whose entire subtree (including inner text and all children) MUST be completely stripped
DANGEROUS_TAGS_WITH_CONTENT: Set[str] = {
    # Active execution and embedding
    "script",
    "style",  # CSS is extracted and sanitized separately; raw <style> in HTML is stripped
    "iframe",
    "object",
    "embed",
    "applet",
    "meta",
    "base",
    "link",
    "noscript",
    "frame",
    "frameset",
    # External media fetch vectors
    "audio",
    "video",
    "source",
    "track",
    # Untrusted SVG and all SVG element descendants (prohibited per security requirements)
    "svg",
    "path",
    "circle",
    "rect",
    "line",
    "polyline",
    "polygon",
    "ellipse",
    "text",
    "tspan",
    "textpath",
    "g",
    "defs",
    "clippath",
    "lineargradient",
    "radialgradient",
    "stop",
    "use",
    "foreignobject",
    "image",
    "marker",
    "pattern",
    "mask",
    "symbol",
    "view",
    # Untrusted MathML and all MathML descendants (prohibited per security requirements)
    "math",
    "semantics",
    "annotation",
    "mtext",
    "mi",
    "mo",
    "mn",
    "ms",
    "mspace",
    "mrow",
    "mfrac",
    "msqrt",
    "mroot",
    "msub",
    "msup",
    "msubsup",
}

# Tags stripped as elements, but their textual children are preserved
DISALLOWED_CONTAINER_TAGS: Set[str] = {
    "form",
    "dialog",
}

# Allowed semantic HTML layout, text hierarchy, and table tags
SAFE_HTML_TAGS: Set[str] = {
    # Structural & Layout
    "div",
    "span",
    "header",
    "footer",
    "nav",
    "main",
    "section",
    "article",
    "aside",
    "figure",
    "figcaption",
    "address",
    # Text Hierarchy & Formatting
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "strike",
    "small",
    "sub",
    "sup",
    "mark",
    "code",
    "pre",
    "blockquote",
    "q",
    "cite",
    "abbr",
    "hr",
    "br",
    "wbr",
    # Lists
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    # Tables
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "colgroup",
    "col",
    # Safe Display Elements
    "img",
    "a",
    "button",
    "label",
    "input",
    "select",
    "option",
    "textarea",
    "progress",
    "meter",
    "details",
    "summary",
}

# Safe generic attributes allowed on safe tags
SAFE_GLOBAL_ATTRIBUTES: Set[str] = {
    "id",
    "class",
    "style",  # Style declarations are separately sanitized
    "title",
    "lang",
    "dir",
    "role",
    "aria-label",
    "aria-labelledby",
    "aria-describedby",
    "aria-hidden",
    "aria-expanded",
    "aria-controls",
    "aria-current",
    "aria-live",
    "tabindex",
}

# Tag-specific allowed attributes
SAFE_TAG_ATTRIBUTES: Dict[str, Set[str]] = {
    "a": {"href", "target", "rel"},
    "img": {"src", "alt", "width", "height", "loading"},
    "button": {"type", "disabled", "name", "value"},
    "input": {"type", "name", "value", "placeholder", "disabled", "readonly", "checked", "min", "max", "step"},
    "select": {"name", "disabled"},
    "option": {"value", "selected"},
    "textarea": {"name", "placeholder", "rows", "cols", "disabled", "readonly"},
    "table": {"border", "cellpadding", "cellspacing"},
    "th": {"scope", "colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "col": {"span"},
    "colgroup": {"span"},
    "progress": {"value", "max"},
    "meter": {"value", "min", "max", "low", "high", "optimum"},
    "details": {"open"},
}

# Void tags in HTML5 that do not have closing tags
VOID_TAGS: Set[str] = {
    "area", "base", "br", "col", "embed", "frame", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


def normalize_and_detect_executable_url(url: str) -> bool:
    """Detect if a URL contains executable schemes, even if obfuscated or entity-encoded.

    Handles mixed-case protocols, whitespace separation, control characters,
    HTML entity encoding, and percent encoding.
    """
    if not url:
        return False

    # 1. Decode HTML entities and URL encodings iteratively
    decoded = unescape(url)
    try:
        decoded = unquote(decoded)
    except Exception:
        pass

    # 2. Strip whitespace and non-printable control characters
    cleaned = re.sub(r"[\s\x00-\x1f\x7f-\x9f]+", "", decoded).lower()

    # 3. Check for executable or dangerous protocols
    dangerous_protocols = (
        "javascript:",
        "vbscript:",
        "data:text/html",
        "data:text/javascript",
        "data:application/javascript",
        "data:image/svg+xml",  # SVG data URIs prohibited
        "blob:",
        "file:",
    )
    return any(cleaned.startswith(proto) for proto in dangerous_protocols)


def validate_image_src(src_val: str) -> Tuple[bool, Optional[str]]:
    """Validate image src against external network resource loading and dangerous formats.

    Requirements:
    - NO remote URLs (http://, https://, //, ftp://).
    - ONLY validated, size-limited raster image data URIs (PNG, JPEG, WEBP, GIF).
    - NO SVG data URIs (data:image/svg+xml).

    Returns:
        Tuple of (is_valid, error_reason).
    """
    if not src_val or not src_val.strip():
        return False, "Empty image src"

    val_clean = src_val.strip()

    # Check for executable schemes
    if normalize_and_detect_executable_url(val_clean):
        return False, "Executable URL scheme in image src"

    # Block remote external URLs (prevents network requests)
    normalized_proto = re.sub(r"[\s\x00-\x1f]+", "", unescape(val_clean)).lower()
    if re.match(r"^(?:https?:|\/\/|ftp:)", normalized_proto):
        return False, "Remote external image URL prohibited"

    # If data: URI, enforce strict raster format and size limits
    if normalized_proto.startswith("data:"):
        # Explicitly forbid SVG data URIs
        if "image/svg" in normalized_proto:
            return False, "SVG data URI prohibited"

        # Enforce size ceiling
        if len(val_clean) > MAX_IMAGE_DATA_URI_CHARS:
            return False, f"Image data URI exceeds size limit ({len(val_clean)} > {MAX_IMAGE_DATA_URI_CHARS})"

        # Strictly allow raster base64 formats
        raster_pattern = r"^data:image\/(?:png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=]+$"
        if not re.match(raster_pattern, val_clean, re.IGNORECASE):
            return False, "Invalid or non-raster image data URI format"

        return True, None

    # Block all other non-data URL schemes in image src
    return False, "Non-local image src prohibited"


class HTMLSanitizingParser(HTMLParser):
    """Robust HTML parser that enforces an allowlist and drops dangerous subtrees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: List[str] = []
        self.diagnostics: List[str] = []
        self._suppress_stack: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        lower_tag = tag.lower().strip()

        # 1. Check if currently inside a suppressed dangerous element (e.g. <script>, <svg>, <math>)
        if self._suppress_stack:
            # Track nested dangerous tags of the same or different kind (only if non-void)
            if lower_tag in DANGEROUS_TAGS_WITH_CONTENT and lower_tag not in VOID_TAGS:
                self._suppress_stack.append(lower_tag)
            return

        # 2. Check if this tag must be completely suppressed along with its subtree
        if lower_tag in DANGEROUS_TAGS_WITH_CONTENT:
            self.diagnostics.append(f"Removed disallowed element <{lower_tag}> and all its descendants")
            if lower_tag not in VOID_TAGS:
                self._suppress_stack.append(lower_tag)
            return

        # 3. Disallowed container tags (e.g. <form>): strip the tag itself, but preserve content
        if lower_tag in DISALLOWED_CONTAINER_TAGS:
            self.diagnostics.append(f"Stripped active container tag <{lower_tag}>")
            return

        # 4. Filter unapproved tags
        if lower_tag not in SAFE_HTML_TAGS:
            self.diagnostics.append(f"Filtered unapproved tag <{lower_tag}>")
            return

        # 5. Sanitize element attributes
        sanitized_attrs: List[Tuple[str, str]] = []
        allowed_tag_attrs = SAFE_TAG_ATTRIBUTES.get(lower_tag, set())

        for attr_name, attr_value in attrs:
            if not attr_name:
                continue
            lower_attr = attr_name.lower().strip()
            val_str = (attr_value or "").strip()

            # Prohibit any inline JavaScript event handler (starts with 'on')
            if lower_attr.startswith("on"):
                self.diagnostics.append(f"Removed inline event handler '{lower_attr}' from <{lower_tag}>")
                continue

            # Prohibit download attributes (prevents forced file downloads)
            if lower_attr in ("download", "formaction", "formmethod", "formenctype", "formtarget"):
                self.diagnostics.append(f"Removed active attribute '{lower_attr}' from <{lower_tag}>")
                continue

            # Verify attribute is in the approved set for this tag or global safe attributes
            is_allowed = (
                lower_attr in SAFE_GLOBAL_ATTRIBUTES
                or lower_attr in allowed_tag_attrs
                or lower_attr.startswith("data-")  # data-* attributes safe for styling/selectors
            )

            if not is_allowed:
                self.diagnostics.append(f"Removed unapproved attribute '{lower_attr}' from <{lower_tag}>")
                continue

            # Validate links in href
            if lower_attr == "href":
                if normalize_and_detect_executable_url(val_str):
                    self.diagnostics.append(f"Blocked executable URL scheme in href on <{lower_tag}>")
                    continue
                # Block remote URLs in href that use dangerous schemes
                norm_val = re.sub(r"[\s\x00-\x1f]+", "", unescape(val_str)).lower()
                if norm_val.startswith("data:"):
                    self.diagnostics.append(f"Blocked data URI in href on <{lower_tag}>")
                    continue

            # Validate image src against external network resource loading
            if lower_tag == "img" and lower_attr == "src":
                is_valid_img, img_err = validate_image_src(val_str)
                if not is_valid_img:
                    self.diagnostics.append(f"Blocked image src: {img_err}")
                    continue

            # Sanitize inline style attributes
            if lower_attr == "style":
                cleaned_style, style_diags = sanitize_inline_style(val_str)
                self.diagnostics.extend(style_diags)
                if not cleaned_style:
                    continue
                val_str = cleaned_style

            # Enforce non-submitting button type
            if lower_tag == "button" and lower_attr == "type" and val_str.lower() in ("submit", ""):
                val_str = "button"

            # Enforce safe input types (never submit)
            if lower_tag == "input" and lower_attr == "type" and val_str.lower() in ("submit", "image"):
                val_str = "button"

            # Enforce target="_blank" safe attributes (prevent tab-napping)
            if lower_tag == "a" and lower_attr == "target" and val_str.lower() == "_blank":
                sanitized_attrs.append(("rel", "noopener noreferrer"))

            sanitized_attrs.append((lower_attr, val_str))

        # Build clean opening tag
        attr_parts = []
        for a_name, a_val in sanitized_attrs:
            attr_parts.append(f'{a_name}="{escape(a_val, quote=True)}"')

        attrs_str = f" {' '.join(attr_parts)}" if attr_parts else ""
        self.output.append(f"<{lower_tag}{attrs_str}>")

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower().strip()

        # Handle suppressed element closing
        if self._suppress_stack:
            if lower_tag in self._suppress_stack:
                # Pop up to and including lower_tag to handle unclosed nested tags
                idx = len(self._suppress_stack) - 1 - self._suppress_stack[::-1].index(lower_tag)
                self._suppress_stack = self._suppress_stack[:idx]
            return

        if lower_tag in DISALLOWED_CONTAINER_TAGS or lower_tag not in SAFE_HTML_TAGS:
            return

        if lower_tag not in VOID_TAGS:
            self.output.append(f"</{lower_tag}>")

    def handle_data(self, data: str) -> None:
        if self._suppress_stack:
            return
        self.output.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if self._suppress_stack:
            return
        self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._suppress_stack:
            return
        self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        # Strip all HTML comments to eliminate parser evasions
        pass


def sanitize_inline_style(style_text: str) -> Tuple[str, List[str]]:
    """Sanitize individual CSS declarations within an HTML element's style attribute."""
    diagnostics: List[str] = []
    if not style_text or not style_text.strip():
        return "", []

    cleaned = style_text

    # Block expression(...)
    if re.search(r"expression\s*\(", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"expression\s*\([^)]*\)", "", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Stripped CSS expression from inline style")

    # Block -moz-binding and behavior
    if re.search(r"-(?:moz-)?binding|behavior", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"-(?:moz-)?binding\s*:[^;]+;?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"behavior\s*:[^;]+;?", "", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Stripped dangerous binding/behavior from inline style")

    # Block javascript: in style
    if re.search(r"javascript\s*:", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"url\s*\([^)]*javascript:[^)]*\)", "none", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"javascript\s*:[^;]+;?", "", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Stripped javascript: scheme from inline style")

    # Block all remote external URLs in url(...)
    if re.search(r"url\s*\(\s*['\"]?\s*(?:https?:|\/\/|ftp:)", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"url\s*\(\s*['\"]?\s*(?:https?:|\/\/|ftp:)[^)]*\)", "none", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Blocked external remote URL in inline style")

    # Block SVG data URIs in inline style url(...)
    if re.search(r"url\s*\(\s*['\"]?\s*data:image\/svg", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"url\s*\(\s*['\"]?\s*data:image\/svg[^)]*\)", "none", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Blocked SVG data URI in inline style")

    return cleaned.strip(), diagnostics


def sanitize_html(raw_html: str) -> Tuple[str, List[str]]:
    """Sanitize raw HTML string through an AST/token parser to guarantee static safety.

    Args:
        raw_html: Untrusted HTML string generated by AI model.

    Returns:
        Tuple of (clean_sanitized_html, list_of_diagnostics).
    """
    if not raw_html or not raw_html.strip():
        return "", []

    cleaned = raw_html.strip()
    # Remove <!DOCTYPE ...>
    cleaned = re.sub(r"<!DOCTYPE[^>]*>", "", cleaned, flags=re.IGNORECASE)
    # Remove <html>, <head>, <body> tags to isolate content fragment (with word boundary so <header> is preserved)
    cleaned = re.sub(r"<\/?(?:html|head|body)\b[^>]*>", "", cleaned, flags=re.IGNORECASE)

    parser = HTMLSanitizingParser()
    try:
        parser.feed(cleaned)
        parser.close()
    except Exception as e:
        return f'<div class="artifact-fallback">{escape(cleaned)}</div>', [f"HTML parse error: {str(e)}"]

    sanitized = "".join(parser.output).strip()
    return sanitized, parser.diagnostics


def sanitize_css(raw_css: str) -> Tuple[str, List[str]]:
    """Sanitize CSS stylesheet against remote imports, external network requests, and expressions.

    Enforces:
    - No remote @import rules.
    - No remote URLs in url(...) (blocks all http://, https://, //, and external fonts/images).
    - No SVG data URIs in url(...).
    - No CSS expressions or dangerous browser behaviors.

    Args:
        raw_css: Untrusted CSS string generated by AI model.

    Returns:
        Tuple of (clean_sanitized_css, list_of_diagnostics).
    """
    if not raw_css or not raw_css.strip():
        return "", []

    diagnostics: List[str] = []
    cleaned = raw_css

    # Strip comments to prevent comment-splitting filter evasions (e.g., exp/* */ression)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)

    # 1. Reject and strip all @import rules (prevents loading remote stylesheets or fonts)
    if re.search(r"@import\b", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"@import\s+[^;]+;?", "", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Stripped disallowed @import rule from CSS")

    # 2. Block CSS expressions (legacy script execution vector)
    if re.search(r"expression\s*\(", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"expression\s*\([^)]*\)", "", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Stripped dangerous CSS expression from stylesheet")

    # 3. Block -moz-binding (XBL injection vector)
    if re.search(r"-moz-binding\s*:", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"-moz-binding\s*:[^;]+;?", "", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Stripped -moz-binding directive from CSS")

    # 4. Block behavior property (HTC component vector)
    if re.search(r"\bbehavior\s*:", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"\bbehavior\s*:[^;]+;?", "", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Stripped behavior property from CSS")

    # 5. Block javascript: pseudo-protocols inside url(...)
    if re.search(r"url\s*\(\s*['\"]?\s*javascript:", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"url\s*\(\s*['\"]?\s*javascript:[^)]*\)", "none", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Blocked javascript: URL scheme in CSS url()")

    # 6. Block remote HTTP/HTTPS/FTP resource fetches in url() to prevent external network requests
    if re.search(r"url\s*\(\s*['\"]?\s*(?:https?:|\/\/|ftp:)", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"url\s*\(\s*['\"]?\s*(?:https?:|\/\/|ftp:)[^)]*\)", "none", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Blocked remote external network resource in CSS url()")

    # 7. Block SVG data URIs in CSS url()
    if re.search(r"url\s*\(\s*['\"]?\s*data:image\/svg", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"url\s*\(\s*['\"]?\s*data:image\/svg[^)]*\)", "none", cleaned, flags=re.IGNORECASE)
        diagnostics.append("Blocked SVG data URI in CSS url()")

    return cleaned.strip(), diagnostics


def build_sandboxed_preview(
    html: str,
    css: str,
    title: str = "Artifact Preview",
) -> str:
    """Assemble a self-contained, securely isolated HTML document for iframe preview.

    Enforces an ultra-strict Content-Security-Policy that guarantees:
    - Zero remote network requests (no remote images, no remote fonts, no remote scripts).
    - Zero script execution.
    - Zero frame embedding or form submissions.
    """
    safe_title = escape(title or "Artifact Preview")

    # Ultra-strict Content Security Policy for static preview isolation
    csp = (
        "default-src 'none'; "
        "style-src 'unsafe-inline'; "
        "img-src data:; "
        "font-src 'none'; "
        "connect-src 'none'; "
        "media-src 'none'; "
        "object-src 'none'; "
        "frame-src 'none'; "
        "child-src 'none'; "
        "form-action 'none'; "
        "base-uri 'none';"
    )

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"UTF-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        f"  <meta http-equiv=\"Content-Security-Policy\" content=\"{csp}\">\n"
        f"  <title>{safe_title}</title>\n"
        "  <style>\n"
        "    /* Base reset for preview isolation */\n"
        "    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "    body {\n"
        "      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;\n"
        "      line-height: 1.5;\n"
        "      color: #111827;\n"
        "      background-color: #ffffff;\n"
        "      padding: 1.5rem;\n"
        "    }\n"
        f"    {css}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  {html}\n"
        "</body>\n"
        "</html>"
    )
