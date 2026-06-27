<script lang="ts">
	import Highlight from '$lib/components/Highlight.svelte';

	type Rule = { id: number; mode: string } | null;
	type Ref = { id: number; name: string; rule: Rule };

	type BookCardData = {
		book_id?: number;
		asin: string;
		title: string;
		image_url?: string | null;
		runtime_minutes: number | null;
		percent_complete: number;
		is_finished: boolean | null;
		user_rating: number | null;
		user_manual_rating?: number | null;
		taste_excluded?: boolean;
		authors?: string;
		narrators?: string;
		authors_ref?: Ref[];
		narrators_ref?: Ref[];
		categories?: Ref[];
		series?: Ref[];
		title_rule?: Rule;
	};

	export type RuleAction =
		| { scope: string; entity_id: number; mode: 'exclude' | 'include' }
		| { deleteId: number };

	let {
		book,
		query = '',
		onRate,
		onClearRating,
		onRule
	}: {
		book: BookCardData;
		query?: string;
		onRate?: (rating: number) => void;
		onClearRating?: () => void;
		onRule?: (action: RuleAction) => void;
	} = $props();

	let imageFailed = $state(false);

	function formatRuntime(minutes: number | null): string {
		if (minutes == null) return '';
		const h = Math.floor(minutes / 60);
		const m = minutes % 60;
		if (h === 0) return `${m}m`;
		return m > 0 ? `${h}h ${m}m` : `${h}h`;
	}

	const SCOPE_LABEL: Record<string, string> = {
		title: 'Title',
		author: 'Author',
		narrator: 'Narrator',
		category: 'Genre',
		series: 'Series'
	};

	type Target = { scope: string; id: number; name: string; rule: Rule };

	const tasteTargets = $derived.by<Target[]>(() => {
		const t: Target[] = [];
		if (book.book_id != null) {
			t.push({ scope: 'title', id: book.book_id, name: book.title, rule: book.title_rule ?? null });
		}
		const groups: [string, Ref[] | undefined][] = [
			['author', book.authors_ref],
			['narrator', book.narrators_ref],
			['category', book.categories],
			['series', book.series]
		];
		for (const [scope, refs] of groups) {
			for (const r of refs ?? []) t.push({ scope, id: r.id, name: r.name, rule: r.rule });
		}
		return t;
	});

	function toggleTitle() {
		if (!onRule || book.book_id == null) return;
		onRule(book.title_rule ? { deleteId: book.title_rule.id } : { scope: 'title', entity_id: book.book_id, mode: 'exclude' });
	}
</script>

<div class="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30">
	<div class="flex gap-4">
		<a
			href="/books/{book.asin}"
			class="flex h-32 w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-muted/40"
			aria-label={book.title}
		>
			{#if book.image_url && !imageFailed}
				<img
					src={book.image_url}
					alt="Cover for {book.title}"
					loading="lazy"
					onerror={() => { imageFailed = true; }}
					class="h-full w-full object-cover"
				/>
			{:else}
				<span class="px-2 text-center font-heading text-3xl text-muted-foreground/60">{book.title.slice(0, 1)}</span>
			{/if}
		</a>

		<div class="min-w-0 flex-1">
			<a href="/books/{book.asin}" class="font-heading text-base font-semibold leading-snug text-card-foreground hover:text-primary">
				<Highlight text={book.title} {query} />
			</a>

			{#if book.series && book.series.length > 0}
				<p class="mt-1 text-xs font-medium text-primary">
					{#each book.series as s, i (s.id)}<a href="/series/{s.id}" class="hover:underline">{s.name}</a>{#if i < book.series.length - 1}, {/if}{/each}
				</p>
			{/if}

			{#if book.authors}
				<p class="mt-2 text-sm text-muted-foreground">
					by <Highlight text={book.authors} {query} />
				</p>
			{/if}
			{#if book.narrators}
				<p class="text-sm text-muted-foreground">
					Narrated by <Highlight text={book.narrators} {query} />
				</p>
			{/if}
		</div>
	</div>

	<div class="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
		{#if book.runtime_minutes}
			<span>{formatRuntime(book.runtime_minutes)}</span>
		{/if}
		{#if book.user_rating != null}
			<span class="flex items-center gap-1">
				<span class="text-primary">★</span>
				{book.user_rating}
			</span>
		{/if}
		{#if book.is_finished}
			<span class="rounded-md bg-primary/10 px-2 py-0.5 font-medium text-primary">
				Finished
			</span>
		{/if}
	</div>

	{#if onRate}
		<div class="mt-3 flex items-center gap-0.5" aria-label="Your rating">
			{#each [1, 2, 3, 4, 5] as star (star)}
				<button
					type="button"
					onclick={() => onRate(star)}
					aria-label={`Rate ${star} star${star > 1 ? 's' : ''}`}
					class="text-lg leading-none transition-colors hover:text-primary {(book.user_manual_rating ?? 0) >= star ? 'text-primary' : 'text-muted-foreground/40'}"
				>
					★
				</button>
			{/each}
			{#if book.user_manual_rating != null}
				<button
					type="button"
					onclick={() => onClearRating?.()}
					class="ml-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
				>
					Clear
				</button>
			{/if}
		</div>
	{/if}

	{#if book.percent_complete > 0 && !book.is_finished}
		<div class="mt-3">
			<div class="flex items-center justify-between text-xs text-muted-foreground">
				<span>Progress</span>
				<span>{Math.round(book.percent_complete)}%</span>
			</div>
			<div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
				<div
					class="h-full rounded-full bg-primary transition-all"
					style="width: {book.percent_complete}%"
				></div>
			</div>
		</div>
	{/if}

	{#if onRule}
		<div class="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
			{#if book.taste_excluded}
				<span class="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
					Excluded from taste
				</span>
			{/if}

			<button
				type="button"
				onclick={toggleTitle}
				class="text-xs font-medium {book.title_rule ? 'text-primary' : 'text-muted-foreground'} transition-colors hover:text-foreground"
			>
				{book.title_rule ? 'Clear title rule' : 'Exclude from taste'}
			</button>

			<details class="relative ml-auto text-xs">
				<summary class="cursor-pointer list-none text-muted-foreground transition-colors hover:text-foreground">
					Taste ▾
				</summary>
				<div class="absolute right-0 z-10 mt-1 w-64 rounded-lg border border-border bg-card p-2 shadow-lg">
					{#each tasteTargets as t (t.scope + ':' + t.id)}
						<div class="flex items-center justify-between gap-2 rounded px-1.5 py-1 hover:bg-muted/50">
							<span class="min-w-0 flex-1 truncate" title={t.name}>
								<span class="text-muted-foreground">{SCOPE_LABEL[t.scope]}:</span>
								{t.name}
								{#if t.rule}
									<span class="text-primary">({t.rule.mode})</span>
								{/if}
							</span>
							<span class="flex shrink-0 items-center gap-1">
								<button
									type="button"
									onclick={() => onRule?.({ scope: t.scope, entity_id: t.id, mode: 'exclude' })}
									class="rounded px-1 text-muted-foreground hover:text-destructive"
									title="Exclude">–</button>
								<button
									type="button"
									onclick={() => onRule?.({ scope: t.scope, entity_id: t.id, mode: 'include' })}
									class="rounded px-1 text-muted-foreground hover:text-primary"
									title="Include">+</button>
								{#if t.rule}
									<button
										type="button"
										onclick={() => onRule?.({ deleteId: t.rule!.id })}
										class="rounded px-1 text-muted-foreground hover:text-foreground"
										title="Clear">×</button>
								{/if}
							</span>
						</div>
					{/each}
				</div>
			</details>
		</div>
	{/if}
</div>
