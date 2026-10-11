import React from 'react';

/**
 * Validate and sanitize URLs to prevent javascript: or data: injection.
 * Only http, https, and relative URLs are permitted.
 * @param {string} url
 * @returns {string} Safe URL or '#'
 */
export function sanitizeUrl(url) {
  if (!url || typeof url !== 'string') return '#';
  const trimmed = url.trim();
  if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith('/')) {
    return trimmed;
  }
  return '#';
}

/**
 * Parse inline Markdown elements into safe React JSX nodes.
 * Supports: bold (**text**), italic (*text*), code (`code`),
 * links ([text](url)), citation tags ([1], [1, 2]), and plain text.
 *
 * @param {string} text
 * @param {string} keyPrefix
 * @returns {Array<React.ReactNode>}
 */
function parseInline(text, keyPrefix = 'inline') {
  if (!text) return [];

  // Match:
  // 1. Inline code: `...`
  // 2. Bold: **...**
  // 3. Italic: *...*
  // 4. Links: [text](url) - supporting nested brackets in label e.g. [Title [at 24:29]](url)
  // 5. Citation tags: [1] or [1-3] or [1, 2]
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[((?:\[[^\]]*\]|[^\[\]])+)\]\(([^\s)]+)\))|(\[\d+(?:[,\s–-]+\d+)*\])/g;

  const elements = [];
  let lastIndex = 0;
  let matchIndex = 0;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    // Append preceding plain text
    if (match.index > lastIndex) {
      elements.push(text.substring(lastIndex, match.index));
    }

    const matchedStr = match[0];
    const key = `${keyPrefix}-${matchIndex++}`;

    if (matchedStr.startsWith('`') && matchedStr.endsWith('`')) {
      // Inline code
      elements.push(
        <code key={key} className="inline-code">
          {matchedStr.slice(1, -1)}
        </code>
      );
    } else if (matchedStr.startsWith('**') && matchedStr.endsWith('**')) {
      // Bold
      elements.push(
        <strong key={key}>
          {parseInline(matchedStr.slice(2, -2), `${key}-b`)}
        </strong>
      );
    } else if (matchedStr.startsWith('*') && matchedStr.endsWith('*')) {
      // Italic
      elements.push(
        <em key={key}>
          {parseInline(matchedStr.slice(1, -1), `${key}-i`)}
        </em>
      );
    } else if (matchedStr.startsWith('[') && matchedStr.includes('](')) {
      // Link [text](url) - supporting nested brackets in label e.g. [Episode [at 24:29]](url)
      const closeBracket = matchedStr.lastIndexOf('](');
      const linkText = matchedStr.slice(1, closeBracket);
      const linkUrl = matchedStr.slice(closeBracket + 2, -1);
      const safeHref = sanitizeUrl(linkUrl);

      elements.push(
        <a
          key={key}
          href={safeHref}
          target="_blank"
          rel="noopener noreferrer"
          className="markdown-link"
        >
          {linkText}
        </a>
      );
    } else if (/^\[\d+(?:[,\s–-]+\d+)*\]$/.test(matchedStr)) {
      // Citation footnote badge
      elements.push(
        <span
          key={key}
          className="citation-ref-badge"
          title={`Podcast citation ${matchedStr}`}
        >
          {matchedStr}
        </span>
      );
    } else {
      elements.push(matchedStr);
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    elements.push(text.substring(lastIndex));
  }

  return elements;
}

/**
 * SafeMarkdown: A pure-React zero-dependency Markdown parser.
 * Renders paragraphs, headings, lists, code blocks, blockquotes, and links
 * safely into native JSX without dangerouslySetInnerHTML.
 */
export default function SafeMarkdown({ content }) {
  if (!content) return null;

  const lines = content.split('\n');
  const blocks = [];
  let blockKey = 0;

  let inCodeBlock = false;
  let codeLang = '';
  let codeBuffer = [];

  let inList = false;
  let listType = 'ul'; // 'ul' | 'ol'
  let listItems = [];

  let inQuote = false;
  let quoteBuffer = [];

  const flushList = () => {
    if (inList && listItems.length > 0) {
      const ListTag = listType === 'ol' ? 'ol' : 'ul';
      blocks.push(
        <ListTag key={`list-${blockKey++}`} className="markdown-list">
          {listItems.map((item, idx) => (
            <li key={`li-${idx}`}>{parseInline(item, `li-${blockKey}-${idx}`)}</li>
          ))}
        </ListTag>
      );
      listItems = [];
      inList = false;
    }
  };

  const flushQuote = () => {
    if (inQuote && quoteBuffer.length > 0) {
      blocks.push(
        <blockquote key={`quote-${blockKey++}`} className="markdown-blockquote">
          {quoteBuffer.map((line, idx) => (
            <p key={`qp-${idx}`}>{parseInline(line, `qp-${blockKey}-${idx}`)}</p>
          ))}
        </blockquote>
      );
      quoteBuffer = [];
      inQuote = false;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    // 1. Code blocks (```)
    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        // End of code block
        blocks.push(
          <pre key={`code-${blockKey++}`} className="markdown-pre">
            <code className={codeLang ? `language-${codeLang}` : undefined}>
              {codeBuffer.join('\n')}
            </code>
          </pre>
        );
        codeBuffer = [];
        codeLang = '';
        inCodeBlock = false;
      } else {
        // Start of code block
        flushList();
        flushQuote();
        inCodeBlock = true;
        codeLang = trimmed.slice(3).trim();
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(rawLine);
      continue;
    }

    // 2. Horizontal rule (--- or ***)
    if (/^(\*\*\*|---|___)$/.test(trimmed)) {
      flushList();
      flushQuote();
      blocks.push(<hr key={`hr-${blockKey++}`} className="markdown-hr" />);
      continue;
    }

    // 3. Headings (#, ##, ###, ####)
    if (trimmed.startsWith('#')) {
      flushList();
      flushQuote();

      if (trimmed.startsWith('#### ')) {
        blocks.push(
          <h4 key={`h4-${blockKey++}`} className="markdown-h4">
            {parseInline(trimmed.slice(5), `h4-${blockKey}`)}
          </h4>
        );
        continue;
      }
      if (trimmed.startsWith('### ')) {
        blocks.push(
          <h3 key={`h3-${blockKey++}`} className="markdown-h3">
            {parseInline(trimmed.slice(4), `h3-${blockKey}`)}
          </h3>
        );
        continue;
      }
      if (trimmed.startsWith('## ')) {
        blocks.push(
          <h2 key={`h2-${blockKey++}`} className="markdown-h2">
            {parseInline(trimmed.slice(3), `h2-${blockKey}`)}
          </h2>
        );
        continue;
      }
      if (trimmed.startsWith('# ')) {
        blocks.push(
          <h1 key={`h1-${blockKey++}`} className="markdown-h1">
            {parseInline(trimmed.slice(2), `h1-${blockKey}`)}
          </h1>
        );
        continue;
      }
    }

    // 4. Blockquotes (> ...)
    if (trimmed.startsWith('>')) {
      flushList();
      inQuote = true;
      const quoteLine = trimmed.replace(/^>\s?/, '');
      quoteBuffer.push(quoteLine);
      continue;
    } else {
      flushQuote();
    }

    // 5. Unordered List Items (- or *)
    const ulMatch = trimmed.match(/^[-*]\s+(.*)$/);
    if (ulMatch) {
      if (!inList || listType !== 'ul') {
        flushList();
        inList = true;
        listType = 'ul';
      }
      listItems.push(ulMatch[1]);
      continue;
    }

    // 6. Ordered List Items (1. ...)
    const olMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (olMatch) {
      if (!inList || listType !== 'ol') {
        flushList();
        inList = true;
        listType = 'ol';
      }
      listItems.push(olMatch[1]);
      continue;
    }

    // Non-list line encountered
    flushList();

    // 7. Blank lines / paragraph separators
    if (trimmed === '') {
      continue;
    }

    // 8. Regular text paragraph
    blocks.push(
      <p key={`p-${blockKey++}`} className="markdown-p">
        {parseInline(rawLine, `p-${blockKey}`)}
      </p>
    );
  }

  // Final flushes
  if (inCodeBlock && codeBuffer.length > 0) {
    blocks.push(
      <pre key={`code-${blockKey++}`} className="markdown-pre">
        <code>{codeBuffer.join('\n')}</code>
      </pre>
    );
  }
  flushList();
  flushQuote();

  return <div className="markdown-content">{blocks}</div>;
}
