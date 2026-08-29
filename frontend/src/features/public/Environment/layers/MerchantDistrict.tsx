/**
 * MerchantDistrict — background tree row + the small buildings that
 * flank the main storefront, including the townhouse that fills the
 * gap east of the store. Everything is grounded on the far side of
 * the sidewalk (bases end where the sidewalk begins).
 */
const VB_BOTTOM = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 1440 810",
  preserveAspectRatio: "xMidYMax slice",
} as const;

export function MerchantDistrictLayer() {
  return (
    <svg className="env-layer env-district" {...VB_BOTTOM} aria-hidden="true">

      {/* ═══ VERGE: grass plane from the horizon down to the sidewalk.
              Without it, buildings float on bare sky. ═══ */}
      <rect x="0" y="502" width="1440" height="148" fill="var(--grass-a)" />
      <rect x="0" y="600" width="1440" height="50" fill="var(--grass-b)" />
      <g stroke="#21130E" strokeWidth="3" strokeLinecap="round" opacity="0.08">
        <path d="M60 540 H 300 M480 566 H 760 M900 545 H 1180 M1240 586 H 1430" fill="none" />
      </g>

      {/* background tree row behind the shops */}
      <g className="tree-row">
        {[80, 190, 285, 762, 1170].map((x, i) => (
          <g key={i} className="leaf-sway" style={{ animationDelay: `${i * 1.3}s` }}>
            <rect x={x + 12} y={560} width="9" height="60" fill="#6B4A36" />
            <circle cx={x + 16} cy={536} r={44 - (i % 3) * 5} fill="#5E8A66" opacity={0.85} />
            <circle cx={x - 6} cy={556} r={30} fill="#4C7355" opacity={0.85} />
            <circle cx={x + 38} cy={552} r={28} fill="#6FA379" opacity={0.8} />
          </g>
        ))}
      </g>


      {/* far-left kiosk + bike rack — fills the west end of the street */}
      <g>
        <ellipse cx="118" cy="650" rx="86" ry="9" fill="#301B12" opacity="0.1" />
        <rect x="52" y="520" width="128" height="130" fill="#EAD2A6" stroke="#301B12" strokeWidth="3" />
        <path d="M42 520 l14 -30 h120 l14 30 Z" fill="#D97757" stroke="#301B12" strokeWidth="3" />
        <rect x="70" y="556" width="92" height="56" fill="#FFE7BD" stroke="#301B12" strokeWidth="3" />
        <g stroke="#301B12" strokeWidth="2.2">
          <rect x="80" y="568" width="16" height="20" fill="#70B88A" />
          <rect x="104" y="564" width="13" height="24" fill="#D97757" />
          <rect x="126" y="570" width="18" height="18" fill="#C9A676" />
        </g>
        {/* counter + hanging bags */}
        <rect x="64" y="616" width="104" height="12" fill="#6B4A36" stroke="#301B12" strokeWidth="2.5" />
        <path d="M84 628 v10 M96 628 v12" stroke="#301B12" strokeWidth="3" />
        <path d="M78 638 h14 l-2 12 h-10 Z" fill="#D97757" stroke="#301B12" strokeWidth="2.4" />
        <path d="M94 640 h13 l-2 11 h-9 Z" fill="#C9A676" stroke="#301B12" strokeWidth="2.4" />
        {/* bike rack + one bike leaning */}
        <g stroke="#301B12" strokeWidth="4" strokeLinecap="round">
          <path d="M212 646 v-22 M232 646 v-22" fill="none" />
        </g>
        <circle cx="258" cy="640" r="11" fill="none" stroke="#301B12" strokeWidth="3.4" />
        <circle cx="286" cy="640" r="11" fill="none" stroke="#301B12" strokeWidth="3.4" />
        <path d="M258 640 L270 626 L286 640 M270 626 L276 640" fill="none" stroke="#301B12" strokeWidth="3" />
        <path d="M262 618 h20 l-4 10 h-12 Z" fill="#D97757" stroke="#301B12" strokeWidth="2.6" />
      </g>

      {/* left shop cluster */}
      <g>
        <ellipse cx="200" cy="642" rx="110" ry="10" fill="#301B12" opacity="0.1" />
        <rect x="120" y="500" width="150" height="152" fill="#EFD9AE" />
        <path d="M108 500 h174 l-14 -34 h-146 Z" fill="#B77F5B" />
        <rect x="146" y="536" width="30" height="44" fill="#9DBBA4" stroke="#301B12" strokeWidth="2.5" />
        <rect x="196" y="536" width="30" height="44" fill="#D9A06B" stroke="#301B12" strokeWidth="2.5" />
        <rect x="152" y="596" width="42" height="46" fill="#301B12" />
        <rect x="230" y="512" width="8" height="26" fill="#301B12" opacity="0.55" />

        <ellipse cx="392" cy="644" rx="92" ry="9" fill="#301B12" opacity="0.1" />
        <rect x="320" y="520" width="120" height="132" fill="#F1DFC0" />
        <path d="M310 520 l20 -28 h100 l20 28 Z" fill="#C9856B" />
        <rect x="340" y="550" width="26" height="38" fill="#9DBBA4" stroke="#301B12" strokeWidth="2.5" />
        <rect x="384" y="550" width="26" height="38" fill="#E3B27E" stroke="#301B12" strokeWidth="2.5" />
        <rect x="352" y="600" width="38" height="44" fill="#301B12" />
      </g>

      {/* east townhouse — fills the gap between the store and the
          right cluster; same palette, same ground line (y 650) */}
      <g>
        <ellipse cx="1025" cy="648" rx="128" ry="10" fill="#301B12" opacity="0.1" />
        {/* chimney behind the roof ridge */}
        <rect x="1058" y="420" width="16" height="40" fill="#A9684F" />
        <rect x="1054" y="416" width="24" height="8" fill="#8A5B45" />
        {/* body + pitched roof */}
        <rect x="920" y="478" width="210" height="172" fill="#F1DFC0" />
        <path d="M908 478 l22 -30 h180 l22 30 Z" fill="#B77F5B" />
        {/* upper windows */}
        <rect x="944" y="506" width="32" height="44" fill="#9DBBA4" stroke="#301B12" strokeWidth="2.5" />
        <rect x="1010" y="506" width="32" height="44" fill="#D9A06B" stroke="#301B12" strokeWidth="2.5" />
        <rect x="1076" y="506" width="32" height="44" fill="#9DBBA4" stroke="#301B12" strokeWidth="2.5" />
        {/* ground-floor window + front door, both on the ground line */}
        <rect x="944" y="584" width="56" height="54" fill="#FFE7BD" stroke="#301B12" strokeWidth="2.5" />
        <line x1="944" y1="611" x2="1000" y2="611" stroke="#301B12" strokeWidth="2" />
        <rect x="1040" y="580" width="42" height="70" fill="#301B12" />
        <rect x="1034" y="650" width="54" height="6" fill="#DEC79A" stroke="#301B12" strokeWidth="2.2" />
      </g>

      {/* right cluster */}
      <g>
        <ellipse cx="1305" cy="644" rx="120" ry="10" fill="#301B12" opacity="0.1" />
        <rect x="1230" y="496" width="140" height="156" fill="#F1DFC0" />
        <path d="M1218 496 h164 v-10 h-164 Z" fill="#8FA3B8" />
        <path d="M1226 486 h148 l-12 -26 h-124 Z" fill="#6E8299" />
        <rect x="1254" y="532" width="30" height="46" fill="#9DBBA4" stroke="#301B12" strokeWidth="2.5" />
        <rect x="1304" y="532" width="30" height="46" fill="#D9A06B" stroke="#301B12" strokeWidth="2.5" />
        <rect x="1262" y="596" width="46" height="48" fill="#301B12" />
        <rect x="1348" y="516" width="7" height="22" fill="#301B12" opacity="0.5" />

        <rect x="1392" y="520" width="48" height="132" fill="#EAD2A6" />
        <path d="M1384 520 l14 -24 h50 l14 24 Z" fill="#A9684F" />
        <rect x="1402" y="548" width="28" height="40" fill="#9DBBA4" stroke="#301B12" strokeWidth="2.5" />
      </g>

      {/* district windows glow at night */}
      <g fill="#F6C489" opacity="calc(var(--lamps) * 0.75)">
        <rect x="152" y="544" width="12" height="14" />
        <rect x="202" y="544" width="12" height="14" />
        <rect x="348" y="558" width="11" height="13" />
        {/* townhouse */}
        <rect x="950" y="520" width="12" height="14" />
        <rect x="1016" y="520" width="12" height="14" />
        <rect x="1082" y="520" width="12" height="14" />
        <rect x="950" y="592" width="44" height="38" opacity="calc(var(--lamps) * 0.55)" />
        {/* right cluster */}
        <rect x="1262" y="540" width="12" height="14" />
        <rect x="1310" y="540" width="12" height="14" />
        <rect x="1406" y="556" width="11" height="13" />
      </g>
    </svg>
  );
}
