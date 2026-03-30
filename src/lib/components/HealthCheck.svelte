<script lang="ts">
	import { getHealth } from '$lib/api/health.remote';

	const health = $derived(await getHealth());
</script>

<svelte:boundary>
	<div class="rounded-xl border border-border bg-card p-4">
		<div class="flex items-center gap-2">
			<span class="inline-block h-2.5 w-2.5 rounded-full bg-green-500"></span>
			<span class="text-sm font-medium text-card-foreground">Backend Connected</span>
		</div>
		<p class="mt-2 text-xs text-muted-foreground">
			{health.service} — {health.status}
		</p>
	</div>

	{#snippet pending()}
		<div class="rounded-xl border border-border bg-card p-4 animate-pulse">
			<div class="flex items-center gap-2">
				<span class="inline-block h-2.5 w-2.5 rounded-full bg-muted"></span>
				<span class="text-sm text-muted-foreground">Checking backend…</span>
			</div>
		</div>
	{/snippet}

	{#snippet failed(error, reset)}
		<div class="rounded-xl border border-destructive/50 bg-destructive/10 p-4">
			<div class="flex items-center gap-2">
				<span class="inline-block h-2.5 w-2.5 rounded-full bg-destructive"></span>
				<span class="text-sm font-medium text-destructive">Backend Unavailable</span>
			</div>
			<p class="mt-2 text-xs text-muted-foreground">
				{error instanceof Error ? error.message : 'Unknown error'}
			</p>
			<button
				onclick={reset}
				class="mt-2 text-xs font-medium text-primary underline-offset-4 hover:underline"
			>
				Retry
			</button>
		</div>
	{/snippet}
</svelte:boundary>
