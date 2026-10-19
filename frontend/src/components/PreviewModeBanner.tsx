import { useNavigate } from "react-router-dom";

export interface PreviewModeBannerProps {
  pageName: string;
  description?: string;
  actionText?: string;
  className?: string;
}

export function PreviewModeBanner({
  pageName,
  description = "Sign in with your merchant account to connect live business data and execute real growth actions.",
  actionText = "Sign In →",
  className = "",
}: PreviewModeBannerProps) {
  const navigate = useNavigate();

  return (
    <div className={`rg-preview-banner ${className}`} role="status">
      <div className="rg-preview-banner__icon" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <div className="rg-preview-banner__copy">
        <strong className="rg-preview-banner__title">
          Viewing {pageName} in Preview Mode
        </strong>
        <span className="rg-preview-banner__desc">{description}</span>
      </div>
      <button
        type="button"
        className="rg-preview-banner__btn"
        onClick={() => navigate("/login")}
      >
        {actionText}
      </button>
    </div>
  );
}
