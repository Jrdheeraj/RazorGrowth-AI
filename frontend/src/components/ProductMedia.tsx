/**
 * ProductMedia — the SINGLE reusable product-image presentation system.
 *
 * Every product card in the catalog renders its photography through this
 * component, so all products share one premium e-commerce presentation:
 * a warm-cream image stage, object-fit containment (never cropped or
 * stretched), a subtle hover zoom, a skeleton while loading, a polished
 * fallback when an image fails, and a click-to-open ProductLightbox.
 *
 * DATA CONTRACT (presentation only — never mutates product data):
 *   - `images` accepts the product's EXISTING imagery in any current shape:
 *     a single URL string, an array of URLs, or null when none resolved.
 *     Today every product carries exactly one local photo (see
 *     data/productCatalog.ts, matched by name in Checkout); the component
 *     automatically switches between single-image mode and multi-image
 *     gallery mode (thumbnails, arrows, counter) when more URLs exist.
 *   - No fake secondary images are ever invented: only URLs passed in are
 *     rendered. A product with one image shows one image.
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./ProductMedia.css";

/** Normalise the product's existing imagery to a clean URL list. */
export function resolveProductImages(
  images: string | Array<string | null | undefined> | null | undefined,
): string[] {
  if (!images) return [];
  const list = Array.isArray(images) ? images : [images];
  return list.filter((src): src is string => typeof src === "string" && src.length > 0);
}

/* ── outline icons (1.8px stroke, matches checkout icon language) ───────── */

function MediaIcon({ size = 16, children }: { size?: number; children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const IconImage = () => (
  <MediaIcon size={26}>
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <circle cx="9" cy="10" r="1.8" />
      <path d="M4.5 17.5l4.5-4.5 3 3 3-3 4.5 4.5" />
    </>
  </MediaIcon>
);

const IconZoom = () => (
  <MediaIcon size={13}>
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="M15.5 15.5L20 20" />
      <path d="M11 8.5v5M8.5 11h5" />
    </>
  </MediaIcon>
);

const IconClose = () => (
  <MediaIcon size={15}>
    <>
      <path d="M6 6l12 12M18 6L6 18" />
    </>
  </MediaIcon>
);

const IconPrev = () => (
  <MediaIcon size={17}>
    <>
      <path d="M14.5 5.5L8 12l6.5 6.5" />
    </>
  </MediaIcon>
);

const IconNext = () => (
  <MediaIcon size={17}>
    <>
      <path d="M9.5 5.5L16 12l-6.5 6.5" />
    </>
  </MediaIcon>
);

/* ── ProductLightbox ─────────────────────────────────────────────────────── */

interface ProductLightboxProps {
  images: string[];
  name: string;
  initialIndex: number;
  onClose: () => void;
}

export function ProductLightbox({ images, name, initialIndex, onClose }: ProductLightboxProps) {
  const [index, setIndex] = useState(initialIndex);
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const multi = images.length > 1;
  const active = images[index] ?? null;

  const go = useCallback(
    (dir: 1 | -1) => {
      setIndex((i) => (i + dir + images.length) % images.length);
    },
    [images.length],
  );

  /* Keyboard: ESC closes, arrows navigate (multi-image only). */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (multi && e.key === "ArrowRight") go(1);
      else if (multi && e.key === "ArrowLeft") go(-1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [go, multi, onClose]);

  /* Lock background scroll + focus the close button while open. */
  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  return createPortal(
    <div
      className="rgpm-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="rgpm-viewer">
        <div className="rgpm-viewer__head">
          <p className="rgpm-viewer__name" id={titleId} title={name}>
            {name}
          </p>
          <button
            ref={closeRef}
            type="button"
            className="rgpm-viewer__close"
            onClick={onClose}
            aria-label={`Close image viewer for ${name}`}
          >
            <IconClose />
          </button>
        </div>

        <div className="rgpm-viewer__stage">
          {multi && (
            <button
              type="button"
              className="rgpm-nav rgpm-nav--prev"
              onClick={() => go(-1)}
              aria-label={`Previous image of ${name}`}
            >
              <IconPrev />
            </button>
          )}
          <div className="rgpm-viewer__imgwrap" aria-live="polite">
            {active && !failed[active] ? (
              <img
                key={active}
                className="rgpm-viewer__img"
                src={active}
                alt={multi ? `${name} — image ${index + 1} of ${images.length}` : name}
                onError={() => setFailed((f) => ({ ...f, [active]: true }))}
              />
            ) : (
              <span className="rgpm-fallback rgpm-fallback--viewer" role="img" aria-label={`Image unavailable for ${name}`}>
                <IconImage />
                <span>Image unavailable</span>
              </span>
            )}
          </div>
          {multi && (
            <button
              type="button"
              className="rgpm-nav rgpm-nav--next"
              onClick={() => go(1)}
              aria-label={`Next image of ${name}`}
            >
              <IconNext />
            </button>
          )}
        </div>

        {multi && (
          <div className="rgpm-thumbs" role="group" aria-label={`Thumbnails for ${name}`}>
            {images.map((src, i) => (
              <button
                key={src + i}
                type="button"
                className={`rgpm-thumb${i === index ? " is-sel" : ""}`}
                onClick={() => setIndex(i)}
                aria-label={`View image ${i + 1} of ${images.length} for ${name}`}
                aria-pressed={i === index}
              >
                {!failed[src] ? (
                  <img
                    src={src}
                    alt=""
                    loading="lazy"
                    onError={() => setFailed((f) => ({ ...f, [src]: true }))}
                  />
                ) : (
                  <span className="rgpm-thumb__fallback" aria-hidden="true">
                    <IconImage />
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        {multi && (
          <p className="rgpm-counter" aria-label={`Image ${index + 1} of ${images.length}`}>
            {index + 1} / {images.length}
          </p>
        )}
      </div>
    </div>,
    document.body,
  );
}

/* ── ProductMedia (card stage) ───────────────────────────────────────────── */

interface ProductMediaProps {
  /** The product's EXISTING imagery — single URL, URL array, or null. */
  images: string | Array<string | null | undefined> | null | undefined;
  /** Actual product name — used for alt text and viewer heading. */
  name: string;
}

export function ProductMedia({ images, name }: ProductMediaProps) {
  const list = resolveProductImages(images);
  const primary = list[0] ?? null;
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerIndex, setViewerIndex] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);

  /* Reset per-product state when the card swaps to another product. */
  useEffect(() => {
    setLoaded(false);
    setFailed(false);
    setViewerOpen(false);
    setViewerIndex(0);
  }, [primary]);

  /* Return focus to the card stage when the viewer closes. */
  const closeViewer = useCallback(() => {
    setViewerOpen(false);
    triggerRef.current?.focus();
  }, []);

  const showFallback = failed || !primary;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="rgpm-stage"
        onClick={() => {
          if (primary && !failed) {
            setViewerIndex(0);
            setViewerOpen(true);
          }
        }}
        aria-haspopup="dialog"
        aria-label={primary && !failed ? `View larger images of ${name}` : `${name} — image unavailable`}
      >
        {!loaded && !showFallback && <span className="rgpm-skeleton" aria-hidden="true" />}
        {!showFallback && primary && (
          <img
            className={`rgpm-img${loaded ? " is-loaded" : ""}`}
            src={primary}
            alt={name}
            loading="lazy"
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
          />
        )}
        {showFallback && (
          <span className="rgpm-fallback" role="img" aria-label={`Image unavailable for ${name}`}>
            <IconImage />
            <span>Image unavailable</span>
          </span>
        )}
        {list.length > 1 && (
          <span className="rgpm-meta" aria-hidden="true">
            <span className="rgpm-dots">
              {list.map((src, i) => (
                <i key={src + i} className={i === 0 ? "is-on" : undefined} />
              ))}
            </span>
            <span className="rgpm-count">1 / {list.length}</span>
          </span>
        )}
        {primary && !failed && (
          <span className="rgpm-zoomhint" aria-hidden="true">
            <IconZoom />
          </span>
        )}
      </button>
      {viewerOpen && primary && !failed && (
        <ProductLightbox images={list} name={name} initialIndex={viewerIndex} onClose={closeViewer} />
      )}
    </>
  );
}
