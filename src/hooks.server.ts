import type { HandleFetch } from '@sveltejs/kit';

const BACKEND_ORIGIN = 'http://localhost:8000';
const PROXIED_PREFIXES = ['/api', '/health'];

/**
 * Rewrite relative URLs to the FastAPI backend during SSR.
 * Vite's dev proxy only handles browser-side requests — SvelteKit's
 * server-side fetch bypasses it, so we rewrite here.
 */
export const handleFetch: HandleFetch = async ({ request, fetch, event }) => {
	const url = new URL(request.url);
	const appOrigin = new URL(event.url.origin);

	if (url.origin === appOrigin.origin) {
		const matchesPrefix = PROXIED_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
		if (matchesPrefix) {
			const backendUrl = `${BACKEND_ORIGIN}${url.pathname}${url.search}`;
			const rewritten = new Request(backendUrl, request);
			return fetch(rewritten);
		}
	}

	return fetch(request);
};
