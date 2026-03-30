<script lang="ts">
	type BookCardData = {
		asin: string;
		title: string;
		runtime_minutes: number | null;
		percent_complete: number;
		is_finished: boolean;
		user_rating: number | null;
		authors?: string;
		narrators?: string;
	};

	let { book }: { book: BookCardData } = $props();

	function formatRuntime(minutes: number | null): string {
		if (minutes == null) return '';
		const h = Math.floor(minutes / 60);
		const m = minutes % 60;
		if (h === 0) return `${m}m`;
		return m > 0 ? `${h}h ${m}m` : `${h}h`;
	}
</script>

<div class="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30">
	<a href="/books/{book.asin}" class="font-heading text-base font-semibold leading-snug text-card-foreground hover:text-primary">
		{book.title}
	</a>

	{#if book.authors}
		<p class="mt-2 text-sm text-muted-foreground">
			by {book.authors}
		</p>
	{/if}
	{#if book.narrators}
		<p class="text-sm text-muted-foreground">
			Narrated by {book.narrators}
		</p>
	{/if}

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
</div>
