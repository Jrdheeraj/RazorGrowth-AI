/**
 * Commerce — the storefront itself: awning, stocked display window,
 * door with open/closed plaque, checkout counter, crates and parcels.
 *
 * Life is communicated through objects only: stock accumulates during
 * business hours, interior lights warm up after dark, the plaque flips
 * to closed for the night. No characters.
 */
const VB_BOTTOM = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 1440 810",
  preserveAspectRatio: "xMidYMax slice",
} as const;

export function CommerceLayer() {
  return (
    <svg className="env-layer env-commerce" {...VB_BOTTOM} aria-hidden="true">

      {/* ═══ STOREFRONT ═══ */}
      <g>
        <ellipse cx="560" cy="654" rx="250" ry="13" fill="#301B12" opacity="0.14" />
        <rect x="380" y="330" width="360" height="322" fill="#FFF3DF" stroke="#301B12" strokeWidth="3.5" />
        <g stroke="#301B12" strokeWidth="1.4" opacity="0.12">
          <path d="M380 372 h360 M380 402 h360" fill="none" />
        </g>
        <rect x="362" y="308" width="396" height="24" fill="#301B12" />
        <rect x="372" y="300" width="376" height="10" fill="#C85F43" />

        {/* awning */}
        <path d="M392 352 h336 v32 q0 14 -13 14 h-310 q-13 0 -13 -14 Z"
          fill="#D97757" stroke="#301B12" strokeWidth="3.5" />
        <g opacity="0.26">
          <rect x="430" y="352" width="26" height="44" fill="#301B12" />
          <rect x="492" y="352" width="26" height="46" fill="#301B12" />
          <rect x="554" y="352" width="26" height="46" fill="#301B12" />
          <rect x="616" y="352" width="26" height="44" fill="#301B12" />
        </g>

        {/* display window */}
        <rect x="404" y="428" width="180" height="150" fill="#FFE7BD" stroke="#301B12" strokeWidth="3.5" />
        <line x1="404" y1="472" x2="584" y2="472" stroke="#301B12" strokeWidth="2.5" />
        <line x1="404" y1="520" x2="584" y2="520" stroke="#301B12" strokeWidth="2.5" />
        <g stroke="#301B12" strokeWidth="2.4">
          <rect x="418" y="444" width="22" height="25" fill="#70B88A" />
          <rect x="452" y="438" width="18" height="31" fill="#D97757" />
          <rect x="482" y="446" width="27" height="23" fill="#C9A676" />
          <rect x="521" y="440" width="20" height="29" fill="#B77F5B" />
          <rect x="550" y="446" width="17" height="23" fill="#8FBF9F" />
          <rect x="414" y="494" width="28" height="23" fill="#D97757" />
          <rect x="454" y="498" width="19" height="19" fill="#8FBF9F" />
          <rect x="486" y="492" width="26" height="25" fill="#C9A676" />
          <rect x="526" y="496" width="18" height="21" fill="#B77F5B" />
          <rect x="554" y="494" width="17" height="23" fill="#70B88A" />
          <rect x="424" y="542" width="30" height="25" fill="#C9A676" />
          <rect x="466" y="546" width="22" height="21" fill="#70B88A" />
          <rect x="500" y="540" width="32" height="27" fill="#D97757" />
          <rect x="544" y="546" width="22" height="21" fill="#E3B27E" />
        </g>
        {/* interior warmth after dark */}
        <rect className="win-glow" x="404" y="428" width="180" height="150" fill="#F6C489"
          style={{ opacity: "calc(var(--lamps) * 0.5)" }} />

        {/* door + plaque */}
        <rect x="606" y="452" width="82" height="200" fill="#301B12" />
        <rect x="616" y="464" width="62" height="188" fill="#E8B57E" />
        <rect className="win-glow" x="616" y="464" width="62" height="188" fill="#FFDDA6"
          style={{ opacity: "calc(var(--lamps) * 0.65)" }} />
        <circle cx="668" cy="558" r="4.5" fill="#FFF3DF" />
        {/* doorstep */}
        <rect x="600" y="652" width="94" height="7" fill="#DEC79A" stroke="#301B12" strokeWidth="2.4" />
        {/* hanging plant by the window */}
        <path d="M596 420 v18" stroke="#301B12" strokeWidth="3.4" />
        <path d="M584 438 h24 l-4 16 h-16 Z" fill="#C9855B" stroke="#301B12" strokeWidth="2.8" />
        <g fill="#70B88A">
          <circle cx="589" cy="440" r="4.4" /><circle cx="597" cy="444" r="4.8" />
          <circle cx="604" cy="439" r="4.2" />
        </g>
        <g transform="translate(592 398)">
          <rect width="86" height="34" rx="3" fill="#FFF3DF" stroke="#301B12" strokeWidth="3" />
          <circle cx="18" cy="17" r="7" fill="#70B88A" stroke="#301B12" strokeWidth="2.5"
            style={{ opacity: "var(--store-open)" }} />
          <circle cx="18" cy="17" r="7" fill="#8A6F5C" stroke="#301B12" strokeWidth="2.5"
            style={{ opacity: "calc(1 - var(--store-open))" }} />
          <rect x="34" y="9" width="38" height="4" rx="2" fill="#301B12" opacity="0.75" />
          <rect x="34" y="19" width="28" height="4" rx="2" fill="#301B12" opacity="0.45" />
        </g>

        {/* perpendicular bracket sign */}
        <path d="M380 344 v30 M380 350 h-34" stroke="#301B12" strokeWidth="4" strokeLinecap="round" />
        <rect x="322" y="344" width="26" height="42" rx="3" fill="#FFF3DF" stroke="#301B12" strokeWidth="3" />
        <circle cx="335" cy="358" r="6.5" fill="#D97757" stroke="#301B12" strokeWidth="2.4" />
        <rect x="328" y="370" width="14" height="4" rx="2" fill="#301B12" opacity="0.6" />

        {/* wall lamp */}
        <path d="M742 366 v38" stroke="#301B12" strokeWidth="5" />
        <path d="M730 404 h24 l-5 -14 h-14 Z" fill="#301B12" />
        <circle cx="742" cy="416" r="9" fill="#F6C489" style={{ opacity: "var(--lamps)" }} />

        {/* produce crates outside */}
        <g stroke="#301B12" strokeWidth="3">
          <rect x="338" y="612" width="76" height="42" fill="#C9855B" />
          <circle cx="356" cy="608" r="9" fill="#70B88A" />
          <circle cx="376" cy="604" r="9" fill="#D97757" />
          <circle cx="396" cy="608" r="9" fill="#70B88A" />
          <rect x="424" y="620" width="60" height="34" fill="#D9B98A" />
        </g>
      </g>

      {/* ═══ CHECKOUT ═══ */}
      <g>
        <rect x="694" y="592" width="96" height="10" fill="#6B4A36" stroke="#301B12" strokeWidth="3" />
        <rect x="702" y="602" width="9" height="50" fill="#6B4A36" stroke="#301B12" strokeWidth="3" />
        <rect x="772" y="602" width="9" height="50" fill="#6B4A36" stroke="#301B12" strokeWidth="3" />
        <rect x="706" y="576" width="30" height="16" rx="2" fill="#301B12" />
        <rect x="710" y="568" width="14" height="9" fill="#F6C489" stroke="#301B12" strokeWidth="2" />
      </g>

      {/* ═══ PARCELS BY THE DOOR — stock grows through the day ═══ */}
      <g stroke="#301B12" strokeWidth="3">
        <ellipse cx="806" cy="650" rx="52" ry="8" fill="#301B12" opacity="0.13" />
        <rect x="778" y="618" width="56" height="32" fill="#D9B98A" />
        <line x1="806" y1="618" x2="806" y2="650" />
        <rect x="788" y="594" width="38" height="24" fill="#C9A676"
          style={{ opacity: "calc(0.35 + var(--stock) * 0.65)" }} />
        <rect x="794" y="574" width="26" height="20" fill="#E4CB9E"
          style={{ opacity: "var(--stock-extra)" }} />
      </g>

      {/* ═══ PARKED BICYCLE on the far sidewalk ═══ */}
      <g>
        <ellipse cx="882" cy="651" rx="34" ry="6" fill="#301B12" opacity="0.13" />
        <circle cx="864" cy="641" r="11" fill="none" stroke="#301B12" strokeWidth="3.4" />
        <circle cx="902" cy="641" r="11" fill="none" stroke="#301B12" strokeWidth="3.4" />
        <path d="M864 641 L878 625 L896 625 L902 641 M878 625 L886 641 M874 620 h9"
          fill="none" stroke="#301B12" strokeWidth="3" strokeLinecap="round" />
        <rect x="888" y="612" width="18" height="13" rx="2" fill="#D97757" stroke="#301B12" strokeWidth="2.6" />
      </g>

      {/* doorstep light pool */}
      <ellipse cx="647" cy="655" rx="64" ry="10" fill="#F6C489"
        style={{ opacity: "calc(var(--lamps) * 0.3)" }} />
    </svg>
  );
}
