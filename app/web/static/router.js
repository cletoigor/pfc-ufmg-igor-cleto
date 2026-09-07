// router.js — hash routing for a page with no build step.
//
// Four views live in index.html as sibling <section class="page"> elements;
// the router shows one and hides the rest, then calls that view's render().
// No framework, no History API: a `hashchange` listener and a lookup table is
// the whole mechanism, and the URL stays copy-pasteable.

const routes = new Map();
let currentRoute = null;

export function registerRoute(name, { sectionId, navId, render, title, subtitle }) {
  routes.set(name, { sectionId, navId, render, title, subtitle });
}

export function currentRouteName() {
  return currentRoute;
}

function routeFromHash() {
  const raw = (window.location.hash || "").replace(/^#\/?/, "").split("?")[0];
  return routes.has(raw) ? raw : routes.keys().next().value;
}

/** Re-renders the active view without changing the route (filters changed). */
export function renderActiveRoute() {
  const route = routes.get(currentRoute);
  if (route?.render) route.render();
}

function activate(name) {
  currentRoute = name;

  routes.forEach((route, routeName) => {
    const section = document.getElementById(route.sectionId);
    if (section) section.hidden = routeName !== name;
    const nav = document.getElementById(route.navId);
    if (nav) nav.classList.toggle("is-active", routeName === name);
  });

  const route = routes.get(name);
  const titleEl = document.getElementById("topbar-title");
  if (titleEl && route?.title) titleEl.textContent = route.title;

  // Moving to a view scrolls back to the top; landing halfway down a page you
  // have not seen before is disorienting.
  const scroller = document.querySelector(".main-scroll");
  if (scroller) scroller.scrollTop = 0;

  if (route?.render) route.render();
}

export function startRouter() {
  window.addEventListener("hashchange", () => activate(routeFromHash()));
  if (!window.location.hash) {
    window.location.hash = `#/${routes.keys().next().value}`;
  }
  activate(routeFromHash());
}
