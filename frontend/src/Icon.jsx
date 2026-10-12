import React from 'react';

/**
 * Reusable Lucide-inspired SVG Icon component.
 * Provides a clean outline aesthetic (2px stroke, rounded joints, currentColor inheritance)
 * replacing decorative emojis throughout the enterprise interface.
 */
export default function Icon({
  name,
  size = 16,
  strokeWidth = 2,
  className = '',
  style = {},
  'aria-label': ariaLabel,
  ...props
}) {
  const isAccessible = Boolean(ariaLabel);
  const baseStyle = {
    display: 'inline-flex',
    verticalAlign: 'middle',
    flexShrink: 0,
    ...style,
  };

  const renderIconPath = () => {
    switch (name) {
      case 'mic':
      case 'podcast':
        return (
          <>
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" x2="12" y1="19" y2="22" />
          </>
        );
      case 'monitor':
      case 'laptop':
      case 'local':
        return (
          <>
            <rect width="20" height="14" x="2" y="3" rx="2" />
            <line x1="8" x2="16" y1="21" y2="21" />
            <line x1="12" x2="12" y1="17" y2="21" />
          </>
        );
      case 'cloud':
        return <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />;
      case 'layout':
      case 'artifact':
        return (
          <>
            <rect width="18" height="18" x="3" y="3" rx="2" />
            <path d="M3 9h18" />
            <path d="M9 21V9" />
          </>
        );
      case 'code':
        return (
          <>
            <polyline points="16 18 22 12 16 6" />
            <polyline points="8 6 2 12 8 18" />
          </>
        );
      case 'pen':
      case 'edit':
        return (
          <>
            <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
            <path d="m15 5 4 4" />
          </>
        );
      case 'file-text':
      case 'essay':
        return (
          <>
            <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
            <path d="M14 2v4a2 2 0 0 0 2 2h4" />
            <path d="M10 9H8" />
            <path d="M16 13H8" />
            <path d="M16 17H8" />
          </>
        );
      case 'file':
        return (
          <>
            <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
            <path d="M14 2v4a2 2 0 0 0 2 2h4" />
          </>
        );
      case 'book-open':
      case 'sources':
        return (
          <>
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
          </>
        );
      case 'plus':
        return (
          <>
            <path d="M5 12h14" />
            <path d="M12 5v14" />
          </>
        );
      case 'user':
        return (
          <>
            <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </>
        );
      case 'loader':
      case 'spinner':
        return <path d="M21 12a9 9 0 1 1-6.219-8.56" />;
      case 'alert-triangle':
      case 'warning':
        return (
          <>
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
            <line x1="12" x2="12" y1="9" y2="13" />
            <line x1="12" x2="12.01" y1="17" y2="17" />
          </>
        );
      case 'check':
        return <polyline points="20 6 9 17 4 12" />;
      case 'copy':
        return (
          <>
            <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
            <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
          </>
        );
      case 'eye':
        return (
          <>
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
            <circle cx="12" cy="12" r="3" />
          </>
        );
      case 'sliders':
        return (
          <>
            <line x1="4" x2="4" y1="21" y2="14" />
            <line x1="4" x2="4" y1="10" y2="3" />
            <line x1="12" x2="12" y1="21" y2="12" />
            <line x1="12" x2="12" y1="8" y2="3" />
            <line x1="20" x2="20" y1="21" y2="16" />
            <line x1="20" x2="20" y1="12" y2="3" />
            <line x1="1" x2="7" y1="14" y2="14" />
            <line x1="9" x2="15" y1="8" y2="8" />
            <line x1="17" x2="23" y1="16" y2="16" />
          </>
        );
      case 'sparkles':
      case 'zap':
        return (
          <>
            <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
            <path d="M5 3v4" />
            <path d="M19 17v4" />
            <path d="M3 5h4" />
            <path d="M17 19h4" />
          </>
        );
      case 'shield':
        return <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />;
      case 'clock':
        return (
          <>
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </>
        );
      case 'play':
        return <polygon points="6 3 20 12 6 21 6 3" />;
      case 'external-link':
        return (
          <>
            <path d="M15 3h6v6" />
            <path d="M10 14 21 3" />
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          </>
        );
      case 'chevron-down':
        return <polyline points="6 9 12 15 18 9" />;
      case 'chevron-right':
        return <polyline points="9 18 15 12 9 6" />;
      case 'chevron-up':
        return <polyline points="18 15 12 9 6 15" />;
      case 'folder':
        return (
          <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
        );
      case 'x':
      case 'close':
        return (
          <>
            <path d="M18 6 6 18" />
            <path d="M6 6l12 12" />
          </>
        );
      default:
        return null;
    }
  };

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`app-icon icon-${name} ${className}`}
      style={baseStyle}
      aria-hidden={!isAccessible}
      aria-label={ariaLabel}
      {...props}
    >
      {renderIconPath()}
    </svg>
  );
}

export { Icon };
