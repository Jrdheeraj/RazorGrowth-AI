import { useWorldScroll } from "./useWorldScroll";
import { SkyLayer, StarsLayer, CelestialLayer } from "./layers/Sky";
import { CloudsLayer } from "./layers/Clouds";
import { CityLayer } from "./layers/City";
import { MerchantDistrictLayer } from "./layers/MerchantDistrict";
import { StreetSurfaceLayer } from "./layers/Street";
import { CommerceLayer } from "./layers/Commerce";
import { DeliveryLayer } from "./layers/Delivery";
import { ForegroundLayer } from "./layers/Foreground";
import "./environment.css";

/**
 * EnvironmentScene — one continuous merchant street, painted in strict
 * depth order. The road NEVER crosses buildings: buildings end at the
 * far sidewalk line; sidewalk → curb → road sit in front of them;
 * grounded objects stand on the sidewalk; foreground objects are nearest.
 * No characters — life is told through architecture and objects.
 *
 *   sky · stars · sun/moon · clouds · distant city · district shops ·
 *   SIDEWALK+ROAD · storefront+parcels+bicycle · parked scooter · lamps/front
 */
export function EnvironmentScene() {
  return (
    <div className="env-stack" aria-hidden="true">
      <SkyLayer />
      <StarsLayer />
      <CelestialLayer />
      <CloudsLayer />
      <CityLayer />
      <MerchantDistrictLayer />
      <StreetSurfaceLayer />
      <CommerceLayer />
      <DeliveryLayer />
      <ForegroundLayer />
    </div>
  );
}
