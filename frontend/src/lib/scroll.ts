/** Section-anchor helpers for the single-page public website. */

export function scrollToSection(id: string): boolean {
  const el = document.getElementById(id);
  if (!el) return false;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  return true;
}

export function scrollToTop(): void {
  window.scrollTo({ top: 0, behavior: "smooth" });
}
