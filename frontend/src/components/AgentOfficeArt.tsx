/**
 * AgentOfficeArt — the shared RazorGrowth illustrated storefront office.
 *
 * Extracted verbatim from the Marketing Agent dashboard's hero art so the
 * Product, Marketing, Checkout and Profile dashboards all render the SAME
 * underlying illustration (warm cream paper, thin dark outlines,
 * terracotta accents, square edges) instead of drifting into lookalikes.
 *
 * Only the storefront sign text is parameterized — everything else
 * (composition, colors, line-art, tree, sun, wall tags) stays identical.
 */

interface AgentOfficeArtProps {
  /** Storefront sign-band text. Defaults to the Marketing Agent signage. */
  sign?: string;
  /** SVG class for page-scoped sizing (e.g. "magi-art"). */
  className?: string;
  /** Accessible label for the illustration. */
  label?: string;
}

export function AgentOfficeArt({
  sign = "MARKETING AGENT",
  className = "magi-art",
  label = "Illustrated Marketing Agent office at work",
}: AgentOfficeArtProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 520 360"
      role="img"
      aria-label={label}
    >
      {/* ground */}
      <rect x="24" y="300" width="472" height="26" fill="#EBD9AE" stroke="#2a1810" strokeWidth="3" />
      {/* main shop block */}
      <rect x="70" y="96" width="330" height="208" fill="#FFF3DF" stroke="#2a1810" strokeWidth="3" />
      {/* sign band */}
      <rect x="70" y="96" width="330" height="40" fill="#21130e" stroke="#2a1810" strokeWidth="3" />
      <text x="235" y="122" textAnchor="middle" fontFamily="'IBM Plex Mono',monospace" fontSize="17" letterSpacing="3" fill="#F7EBD7">
        {sign}
      </text>
      {/* awning */}
      <g stroke="#2a1810" strokeWidth="3">
        <rect x="70" y="136" width="47" height="26" fill="#D97757" />
        <rect x="117" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="164" y="136" width="47" height="26" fill="#D97757" />
        <rect x="211" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="258" y="136" width="47" height="26" fill="#D97757" />
        <rect x="305" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="352" y="136" width="48" height="26" fill="#D97757" />
      </g>
      {/* window with agent + laptop */}
      <rect x="96" y="182" width="150" height="102" fill="#F5E6CF" stroke="#2a1810" strokeWidth="3" />
      {/* robot head */}
      <rect x="128" y="202" width="52" height="44" rx="6" fill="#EBD9AE" stroke="#2a1810" strokeWidth="3" />
      <line x1="154" y1="202" x2="154" y2="192" stroke="#2a1810" strokeWidth="3" />
      <circle cx="154" cy="188" r="5" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
      <circle cx="143" cy="221" r="5" fill="#2a1810" />
      <circle cx="165" cy="221" r="5" fill="#2a1810" />
      <rect x="146" y="233" width="16" height="4" fill="#2a1810" />
      {/* laptop */}
      <rect x="192" y="230" width="40" height="28" fill="#301B12" stroke="#2a1810" strokeWidth="3" />
      <rect x="196" y="234" width="32" height="16" fill="#70B88A" />
      <rect x="186" y="258" width="52" height="6" fill="#301B12" stroke="#2a1810" strokeWidth="2.5" />
      {/* desk */}
      <line x1="96" y1="266" x2="246" y2="266" stroke="#2a1810" strokeWidth="3" />
      {/* door */}
      <rect x="266" y="182" width="108" height="122" fill="#F0BC92" stroke="#2a1810" strokeWidth="3" />
      <rect x="278" y="196" width="84" height="56" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
      <circle cx="356" cy="250" r="4" fill="#2a1810" />
      {/* side tree */}
      <rect x="428" y="230" width="16" height="74" fill="#8C7A66" stroke="#2a1810" strokeWidth="3" />
      <circle cx="436" cy="200" r="34" fill="#7BA57F" stroke="#2a1810" strokeWidth="3" />
      <circle cx="414" cy="216" r="18" fill="#7BA57F" stroke="#2a1810" strokeWidth="3" />
      {/* wall tags */}
      <g fontFamily="'IBM Plex Mono',monospace" fontSize="12" letterSpacing="2">
        <rect x="34" y="150" width="86" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="77" y="167" textAnchor="middle" fill="#2a1810">IDEAS</text>
        <rect x="404" y="120" width="102" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="455" y="137" textAnchor="middle" fill="#2a1810">CAMPAIGNS</text>
        <rect x="404" y="262" width="86" height="26" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
        <text x="447" y="279" textAnchor="middle" fill="#21130e">GROWTH</text>
        <rect x="34" y="230" width="88" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="78" y="247" textAnchor="middle" fill="#2a1810">RESULTS</text>
      </g>
      {/* sun */}
      <circle cx="466" cy="52" r="24" fill="#E8936B" stroke="#2a1810" strokeWidth="3" />
    </svg>
  );
}
