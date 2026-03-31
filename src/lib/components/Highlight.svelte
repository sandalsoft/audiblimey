<!--
  Highlight.svelte — wraps substring matches of query words in <mark> tags.
  Usage: <Highlight text="Some Title" query="some" />
-->
<script lang="ts">
	let { text, query }: { text: string; query: string } = $props();

	/**
	 * Split text into segments, marking which ones match query words.
	 * Returns array of { text, highlight } objects.
	 */
	function getSegments(text: string, query: string): Array<{ text: string; highlight: boolean }> {
		if (!query.trim()) return [{ text, highlight: false }];

		// Build regex from query words, longest first to prefer longer matches
		const words = query
			.trim()
			.split(/\s+/)
			.filter((w) => w.length >= 2) // skip single-char noise
			.sort((a, b) => b.length - a.length);

		if (words.length === 0) return [{ text, highlight: false }];

		const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
		const pattern = new RegExp(`(${escaped.join('|')})`, 'gi');

		const segments: Array<{ text: string; highlight: boolean }> = [];
		let lastIndex = 0;

		for (const match of text.matchAll(pattern)) {
			const matchStart = match.index!;
			if (matchStart > lastIndex) {
				segments.push({ text: text.slice(lastIndex, matchStart), highlight: false });
			}
			segments.push({ text: match[0], highlight: true });
			lastIndex = matchStart + match[0].length;
		}

		if (lastIndex < text.length) {
			segments.push({ text: text.slice(lastIndex), highlight: false });
		}

		return segments.length > 0 ? segments : [{ text, highlight: false }];
	}

	const segments = $derived(getSegments(text, query));
</script>

{#each segments as segment}{#if segment.highlight}<mark
			class="rounded-sm bg-[#000] px-0.5 text-[#B0F85E]">{segment.text}</mark>{:else}{segment.text}{/if}{/each}
