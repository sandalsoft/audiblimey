<script lang="ts">
	import { Wand2, Loader2, BookOpen, Check } from 'lucide-svelte';
	import { askRecommendations, type AskResponse, type AskRecommendation } from '$lib/api/recommendations.remote';

	let prompt = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);
	let result = $state<AskResponse | null>(null);

	const EXAMPLES = [
		'I loved House of Suns — what should I read next?',
		'Something lighter than my usual, for a road trip',
		'A fantasy series to start if I liked my 5-star reads'
	];

	async function submit(e?: SubmitEvent) {
		e?.preventDefault();
		const trimmed = prompt.trim();
		if (!trimmed || loading) return;
		loading = true;
		error = null;
		try {
			result = await askRecommendations({ prompt: trimmed });
		} catch (err) {
			error = err instanceof Error ? err.message : 'Something went wrong';
			result = null;
		} finally {
			loading = false;
		}
	}

	function useExample(text: string) {
		prompt = text;
		submit();
	}

	function cardClass(rec: AskRecommendation): string {
		return 'group flex gap-4 rounded-xl border border-border bg-card p-5 transition-colors' +
			(rec.href ? ' hover:border-primary/30' : '');
	}
</script>

<div class="space-y-6">
	<div class="flex items-center gap-3">
		<Wand2 class="h-7 w-7 text-primary" />
		<div>
			<h1 class="font-heading text-3xl font-bold text-foreground">Ask for Recommendations</h1>
			<p class="mt-1 text-sm text-muted-foreground">
				Describe what you're after. Recommendations are tailored to the books you've rated.
			</p>
		</div>
	</div>

	<form onsubmit={submit} class="space-y-3 rounded-xl border border-border bg-card p-4">
		<textarea
			bind:value={prompt}
			rows={3}
			maxlength={2000}
			placeholder="e.g. More cerebral hard sci-fi like the ones I rated 5 stars…"
			class="w-full resize-none rounded-lg border border-border bg-background px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
		></textarea>
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="flex flex-wrap gap-2">
				{#each EXAMPLES as ex}
					<button
						type="button"
						onclick={() => useExample(ex)}
						disabled={loading}
						class="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
					>
						{ex}
					</button>
				{/each}
			</div>
			<button
				type="submit"
				disabled={loading || prompt.trim().length === 0}
				class="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
			>
				{#if loading}
					<Loader2 class="h-4 w-4 animate-spin" />
					Asking…
				{:else}
					<Wand2 class="h-4 w-4" />
					Ask
				{/if}
			</button>
		</div>
	</form>

	{#if error}
		<div class="rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
			<p class="font-heading text-lg text-destructive">Couldn't get recommendations</p>
			<p class="mt-2 text-sm text-muted-foreground">{error}</p>
		</div>
	{:else if loading}
		<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
			{#each { length: 3 } as _}
				<div class="animate-pulse rounded-xl border border-border bg-card p-5">
					<div class="flex items-start gap-3">
						<div class="h-24 w-16 rounded-lg bg-muted"></div>
						<div class="flex-1 space-y-2">
							<div class="h-5 w-3/4 rounded bg-muted"></div>
							<div class="h-4 w-full rounded bg-muted"></div>
							<div class="h-4 w-2/3 rounded bg-muted"></div>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{:else if result}
		{#if result.text}
			<div class="rounded-xl border border-primary/20 bg-primary/5 p-5">
				<p class="whitespace-pre-wrap text-sm leading-relaxed text-card-foreground">{result.text}</p>
				{#if result.rated_count > 0}
					<p class="mt-2 text-xs text-muted-foreground">
						Based on {result.rated_count} book{result.rated_count === 1 ? '' : 's'} you've rated.
					</p>
				{/if}
			</div>
		{/if}

		{#if result.items.length === 0}
			<div class="rounded-xl border border-dashed border-border bg-card p-10 text-center">
				<BookOpen class="mx-auto h-12 w-12 text-muted-foreground/50" />
				<p class="mt-4 font-heading text-lg text-card-foreground">No recommendations</p>
				<p class="mt-2 text-sm text-muted-foreground">
					{result.rated_count === 0
						? 'Rate a few books in your library first — your ratings power these recommendations.'
						: 'Try rephrasing your request.'}
				</p>
			</div>
		{:else}
			<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each result.items as rec (rec.title + rec.author)}
					{#snippet body()}
						<div class="flex h-24 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-muted/40">
							{#if rec.image_url}
								<img src={rec.image_url} alt={`Cover for ${rec.title}`} loading="lazy" class="h-full w-full object-cover" />
							{:else}
								<span class="font-heading text-2xl text-muted-foreground/60">{rec.title.slice(0, 1)}</span>
							{/if}
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-center gap-2">
								<h3 class="font-heading text-base font-semibold leading-snug text-card-foreground {rec.href ? 'group-hover:text-primary' : ''}">
									{rec.title}
								</h3>
								{#if rec.owned}
									<span class="inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
										<Check class="h-3 w-3" /> In library
									</span>
								{/if}
							</div>
							{#if rec.author}
								<p class="mt-1 text-xs text-muted-foreground">by {rec.author}</p>
							{/if}
							<p class="mt-2 text-sm leading-relaxed text-muted-foreground">{rec.reason}</p>
							{#if !rec.href}
								<p class="mt-2 text-xs text-muted-foreground/60">Not in your catalog</p>
							{/if}
						</div>
					{/snippet}

					{#if rec.href}
						<a href={rec.href} class={cardClass(rec)}>{@render body()}</a>
					{:else}
						<div class={cardClass(rec)}>{@render body()}</div>
					{/if}
				{/each}
			</div>
		{/if}
	{/if}
</div>
