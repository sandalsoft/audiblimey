<script lang="ts">
	import { page } from '$app/state';
	import { ArrowLeft } from 'lucide-svelte';
	import { getAuthorProfile } from '$lib/api/library.remote';
	import PersonProfile from '$lib/components/PersonProfile.svelte';
</script>

<a href="/library" class="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
	<ArrowLeft class="h-4 w-4" />
	Back to Library
</a>

<svelte:boundary>
	{@const profileQuery = getAuthorProfile(Number(page.params.id))}
	{@const author = await profileQuery}

	<div class="mt-6 space-y-6">
		<h1 class="font-heading text-3xl font-bold text-foreground">{author.name}</h1>
		<PersonProfile personType="Author" name={author.name} stats={author.stats} books={author.books} />
	</div>

	{#snippet pending()}
		<div class="mt-6 space-y-6 animate-pulse">
			<div class="h-8 w-1/3 rounded bg-muted"></div>
			<div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
				{#each { length: 4 } as _}
					<div class="h-20 rounded-xl border border-border bg-card"></div>
				{/each}
			</div>
			<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each { length: 3 } as _}
					<div class="h-32 rounded-xl border border-border bg-card"></div>
				{/each}
			</div>
		</div>
	{/snippet}

	{#snippet failed(error, reset)}
		<div class="mt-6 rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
			<p class="font-heading text-lg text-destructive">Failed to load author</p>
			<p class="mt-2 text-sm text-muted-foreground">
				{error instanceof Error ? error.message : 'An unexpected error occurred'}
			</p>
			<button
				onclick={reset}
				class="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
			>
				Retry
			</button>
		</div>
	{/snippet}
</svelte:boundary>
