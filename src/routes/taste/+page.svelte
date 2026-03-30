<script lang="ts">
	import { Sparkles, Pencil, X, RefreshCw, Loader2, BookOpen } from 'lucide-svelte';
	import { getTasteProfile, generateTasteProfile, updateTasteProfile } from '$lib/api/taste.remote';

	let editing = $state(false);
	let editText = $state('');
	let generating = $state(false);
	let saving = $state(false);
	let generateError = $state<string | null>(null);
	let saveError = $state<string | null>(null);

	const profileQuery = getTasteProfile();

	function activeText(profile: { profile_text: string | null; profile_edited: string | null }): string | null {
		return profile.profile_edited ?? profile.profile_text;
	}

	function startEdit(currentText: string | null) {
		editText = currentText ?? '';
		editing = true;
		saveError = null;
	}

	function cancelEdit() {
		editing = false;
		editText = '';
		saveError = null;
	}

	async function saveEdit() {
		saving = true;
		saveError = null;
		try {
			await updateTasteProfile(editText).updates(profileQuery);
			editing = false;
		} catch (err) {
			saveError = err instanceof Error ? err.message : 'Failed to save';
		} finally {
			saving = false;
		}
	}

	async function handleGenerate() {
		generating = true;
		generateError = null;
		try {
			await generateTasteProfile().updates(profileQuery);
		} catch (err) {
			generateError = err instanceof Error ? err.message : 'Failed to generate';
		} finally {
			generating = false;
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '';
		const d = new Date(iso);
		return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
	}
</script>

<div class="space-y-6">
	<div class="flex items-center gap-3">
		<Sparkles class="h-7 w-7 text-primary" />
		<h1 class="font-heading text-3xl font-bold text-foreground">Your Taste Profile</h1>
	</div>

	<svelte:boundary>
		{@const result = profileQuery}
		{@const profile = await result}

		{@const text = activeText(profile)}
		{@const isEdited = profile.profile_edited != null}

		{#if text}
			<!-- Profile exists -->
			<div class="rounded-xl border border-border bg-card p-6 space-y-4">
				<!-- Header row -->
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-2">
						<span
							class="rounded-md px-2 py-0.5 text-xs font-medium {isEdited
								? 'bg-accent text-accent-foreground'
								: 'bg-primary/10 text-primary'}"
						>
							{isEdited ? 'Edited' : 'Generated'}
						</span>
						{#if profile.generated_at}
							<span class="text-xs text-muted-foreground">
								{formatDate(profile.generated_at)}
							</span>
						{/if}
						<span class="text-xs text-muted-foreground">
							· {profile.books_included} book{profile.books_included !== 1 ? 's' : ''} analyzed
						</span>
					</div>

					{#if !editing}
						<div class="flex items-center gap-2">
							<button
								onclick={() => startEdit(text)}
								class="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
							>
								<Pencil class="h-3.5 w-3.5" />
								Edit
							</button>
							<button
								onclick={handleGenerate}
								disabled={generating}
								class="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
							>
								{#if generating}
									<Loader2 class="h-3.5 w-3.5 animate-spin" />
									Generating…
								{:else}
									<RefreshCw class="h-3.5 w-3.5" />
									Regenerate
								{/if}
							</button>
						</div>
					{/if}
				</div>

				{#if generateError}
					<p class="text-sm text-destructive">{generateError}</p>
				{/if}

				<!-- Profile content -->
				{#if editing}
					<div class="space-y-3">
						<textarea
							bind:value={editText}
							rows={10}
							class="w-full rounded-lg border border-border bg-background px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						></textarea>
						{#if saveError}
							<p class="text-sm text-destructive">{saveError}</p>
						{/if}
						<div class="flex items-center gap-2">
							<button
								onclick={saveEdit}
								disabled={saving}
								class="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
							>
								{#if saving}
									<Loader2 class="h-4 w-4 animate-spin" />
									Saving…
								{:else}
									Save
								{/if}
							</button>
							<button
								onclick={cancelEdit}
								class="inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
							>
								<X class="h-4 w-4" />
								Cancel
							</button>
						</div>
					</div>
				{:else}
					<p class="whitespace-pre-wrap text-sm leading-relaxed text-card-foreground">{text}</p>
				{/if}
			</div>
		{:else}
			<!-- Empty state — no profile yet -->
			<div class="rounded-xl border border-dashed border-border bg-card p-10 text-center">
				<BookOpen class="mx-auto h-12 w-12 text-muted-foreground/50" />
				<h2 class="mt-4 font-heading text-lg font-semibold text-foreground">
					No taste profile yet
				</h2>
				<p class="mt-2 text-sm text-muted-foreground">
					Generate a profile from your library to see a summary of your reading preferences.
				</p>
				{#if generateError}
					<p class="mt-3 text-sm text-destructive">{generateError}</p>
				{/if}
				<button
					onclick={handleGenerate}
					disabled={generating}
					class="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
				>
					{#if generating}
						<Loader2 class="h-4 w-4 animate-spin" />
						Generating…
					{:else}
						<Sparkles class="h-4 w-4" />
						Generate Taste Profile
					{/if}
				</button>
			</div>
		{/if}

		{#snippet pending()}
			<div class="rounded-xl border border-border bg-card p-6 space-y-4 animate-pulse">
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-2">
						<div class="h-5 w-16 rounded-md bg-muted"></div>
						<div class="h-4 w-24 rounded bg-muted"></div>
					</div>
					<div class="flex gap-2">
						<div class="h-7 w-16 rounded-lg bg-muted"></div>
						<div class="h-7 w-24 rounded-lg bg-muted"></div>
					</div>
				</div>
				<div class="space-y-2">
					<div class="h-4 w-full rounded bg-muted"></div>
					<div class="h-4 w-5/6 rounded bg-muted"></div>
					<div class="h-4 w-4/6 rounded bg-muted"></div>
					<div class="h-4 w-full rounded bg-muted"></div>
					<div class="h-4 w-3/4 rounded bg-muted"></div>
				</div>
			</div>
		{/snippet}

		{#snippet failed(error, reset)}
			<div class="rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
				<p class="font-heading text-lg text-destructive">Failed to load taste profile</p>
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
</div>
