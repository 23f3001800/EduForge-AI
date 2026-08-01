import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type AnchorHTMLAttributes,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  type RefObject,
} from "react";

/**
 * Minimal client-side router built on the platform History API.
 *
 * Only three routes exist (upload, run, viewer), so a dependency like
 * react-router is not justified — a hand-rolled path matcher is a few dozen
 * lines and keeps the bundle small. The one behaviour this *must* get right
 * for H-02 (resumable progress) is that a hard refresh at `/run/:jobId`
 * keeps the job id, which falls out for free from using real paths + the
 * History API rather than in-memory-only state.
 */

type Listener = () => void;
const listeners = new Set<Listener>();

function emit() {
  listeners.forEach((l) => l());
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): string {
  return window.location.pathname;
}

export function navigate(path: string, options?: { replace?: boolean }): void {
  if (window.location.pathname === path) return;
  if (options?.replace) {
    window.history.replaceState(null, "", path);
  } else {
    window.history.pushState(null, "", path);
  }
  emit();
}

if (typeof window !== "undefined") {
  window.addEventListener("popstate", emit);
}

export function usePathname(): string {
  return useSyncExternalStore(subscribe, getSnapshot, () => "/");
}

export interface LinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  to: string;
  replace?: boolean;
  children: ReactNode;
}

/** A same-origin link that navigates via the History API instead of a full
 * page load, but degrades gracefully (real `href`, works with cmd/ctrl-click,
 * middle-click, and screen readers) because it renders a real `<a>`. */
export function Link({ to, replace, onClick, children, ...rest }: LinkProps) {
  const handleClick = useCallback(
    (event: ReactMouseEvent<HTMLAnchorElement>) => {
      onClick?.(event);
      if (event.defaultPrevented) return;
      if (event.button !== 0) return;
      if (event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      navigate(to, { replace });
    },
    [to, replace, onClick],
  );

  return (
    <a href={to} onClick={handleClick} {...rest}>
      {children}
    </a>
  );
}

// --------------------------------------------------------------- route matching

export type RouteParams = Record<string, string>;

interface Route {
  pattern: RegExp;
  keys: string[];
  render: (params: RouteParams) => ReactNode;
}

function compile(path: string): { pattern: RegExp; keys: string[] } {
  const keys: string[] = [];
  const source = path
    .split("/")
    .map((segment) => {
      if (segment.startsWith(":")) {
        keys.push(segment.slice(1));
        return "([^/]+)";
      }
      return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  return { pattern: new RegExp(`^${source}/?$`), keys };
}

const RouteParamsContext = createContext<RouteParams>({});

export function useRouteParams(): RouteParams {
  return useContext(RouteParamsContext);
}

export interface RouteDef {
  path: string;
  element: ReactNode;
}

export function Routes({ routes, notFound }: { routes: RouteDef[]; notFound: ReactNode }) {
  const pathname = usePathname();

  const compiled: Route[] = useMemo(
    () =>
      routes.map((r) => {
        const { pattern, keys } = compile(r.path);
        return { pattern, keys, render: () => r.element };
      }),
    [routes],
  );

  for (const route of compiled) {
    const match = route.pattern.exec(pathname);
    if (match) {
      const params: RouteParams = {};
      route.keys.forEach((key, idx) => {
        params[key] = decodeURIComponent(match[idx + 1]);
      });
      return <RouteParamsContext.Provider value={params}>{route.render(params)}</RouteParamsContext.Provider>;
    }
  }

  return <>{notFound}</>;
}

/** Scrolls to top on route change, and moves focus to the main landmark so
 * keyboard and screen-reader users get the same "new page" cue sighted users
 * get from the scroll — client-side navigation does not do this for free. */
export function useScrollAndFocusOnNavigate(mainRef: RefObject<HTMLElement>) {
  const pathname = usePathname();
  useEffect(() => {
    window.scrollTo(0, 0);
    mainRef.current?.focus();
  }, [pathname, mainRef]);
}
