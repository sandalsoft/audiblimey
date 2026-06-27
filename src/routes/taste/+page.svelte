<script lang="ts">
	import { Sparkles, Pencil, X, RefreshCw, Loader2, BookOpen, Search, Ban } from 'lucide-svelte';
	import {
		getTasteProfile,
		generateTasteProfile,
		updateTasteProfile,
		getTasteRules,
		deleteTasteRule,
		putTasteRule,
		searchTasteEntities,
		type TasteRules
	} from '$lib/api/taste.remote';

	const SCOPE_LABEL: Record<string, string> = {
		title: 'Title',
		author: 'Author',
		narrator: 'Narrator',
		category: 'Genre',
		series: 'Series'
	};

	// Scopes the user can exclude by search (backend "category" = genre).
	type AddScope = 'author' | 'category' | 'title' | 'series';
	const SCOPE_OPTIONS: { value: AddScope; label: string }[] = [
		{ value: 'author', label: 'Author' },
		{ value: 'category', label: 'Genre' },
		{ value: 'title', label: 'Title' },
		{ value: 'series', label: 'Series' }
	];

	const rulesQuery = getTasteRules();
	const rules = $derived(await rulesQuery);

	function flatRules(r: TasteRules) {
		const scopes = ['title', 'author', 'narrator', 'category', 'series'] as const;
		return scopes.flatMap((scope) => r[scope].map((rule) => ({ scope, ...rule })));
	}

	async function removeRule(id: number) {
		await deleteTasteRule(id).updates(rulesQuery);
	}

	// --- Add an exclusion by searching for an entity ---
	let addScope = $state<AddScope>('author');
	let searchText = $state('');
	let searchResults = $state<{ id: number; label: string }[]>([]);
	let searching = $state(false);
	let addError = $state<string | null>(null);
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;

	function scopeLabel(scope: AddScope): string {
		return SCOPE_OPTIONS.find((o) => o.value === scope)?.label ?? scope;
	}

	async function runSearch() {
		const term = searchText.trim();
		if (term.length < 2) {
			searchResults = [];
			searching = false;
			return;
		}
		try {
			const res = await searchTasteEntities({ scope: addScope, q: term });
			searchResults = res.results;
		} catch (err) {
			addError = err instanceof Error ? err.message : 'Search failed';
			searchResults = [];
		} finally {
			searching = false;
		}
	}

	function scheduleSearch() {
		clearTimeout(debounceTimer);
		addError = null;
		if (searchText.trim().length < 2) {
			searchResults = [];
			searching = false;
			return;
		}
		searching = true;
		debounceTimer = setTimeout(runSearch, 250);
	}

	function selectScope(scope: AddScope) {
		addScope = scope;
		scheduleSearch();
	}

	async function addExclusion(entityId: number) {
		addError = null;
		try {
			await putTasteRule({ scope: addScope, entity_id: entityId, mode: 'exclude' }).updates(rulesQuery);
			searchText = '';
			searchResults = [];
		} catch (err) {
			addError = err instanceof Error ? err.message : 'Failed to add exclusion';
		}
	}

	let editing = $state(false);
	let editText = $state('');
	let generating = $state(false);
	let saving = $state(false);
	let generateError = $state<string | null>(null);
	let saveError = $state<string | null>(null);

	const profileQuery = getTasteProfile();
	const profile = $derived(await profileQuery);

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

	<!-- Taste rules -->
	<div class="space-y-3">
		<div>
			<h2 class="font-heading text-xl font-semibold text-foreground">Taste rules</h2>
			<p class="mt-1 text-sm text-muted-foreground">
				Exclusions and includes apply to recommendations immediately. The profile text above
				updates the next time you Regenerate.
			</p>
		</div>

		<!-- Add an exclusion by search -->
		<div class="space-y-3 rounded-lg border border-border bg-card p-4">
			<div class="flex flex-wrap items-center gap-2">
				<span class="text-sm font-medium text-foreground">Exclude a</span>
				{#each SCOPE_OPTIONS as opt (opt.value)}
					<button
						type="button"
						onclick={() => selectScope(opt.value)}
						class="rounded-md border px-2.5 py-1 text-xs font-medium transition-colors {addScope === opt.value
							? 'border-primary bg-primary/10 text-primary'
							: 'border-border text-muted-foreground hover:text-foreground'}"
					>
						{opt.label}
					</button>
				{/each}
			</div>

			<div class="relative">
				<Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
				<input
					type="text"
					bind:value={searchText}
					oninput={scheduleSearch}
					placeholder={`Search ${scopeLabel(addScope).toLowerCase()}s by name…`}
					class="w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
			</div>

			{#if addError}
				<p class="text-sm text-destructive">{addError}</p>
			{/if}

			{#if searching}
				<p class="text-xs text-muted-foreground">Searching…</p>
			{:else if searchText.trim().length >= 2 && searchResults.length === 0}
				<p class="text-xs text-muted-foreground">No matches.</p>
			{:else if searchResults.length > 0}
				<ul class="divide-y divide-border rounded-md border border-border">
					{#each searchResults as result (result.id)}
						<li class="flex items-center justify-between gap-3 px-3 py-2 text-sm">
							<span class="min-w-0 truncate text-card-foreground">{result.label}</span>
							<button
								type="button"
								onclick={() => addExclusion(result.id)}
								class="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
							>
								<Ban class="h-3 w-3" />
								Exclude
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<svelte:boundary>
			{@const list = flatRules(rules)}
			{#if list.length === 0}
				<p class="rounded-lg border border-dashed border-border bg-card p-4 text-sm text-muted-foreground">
					No taste rules yet. Use the search above to exclude an author, genre, title, or series —
					or add rules from the Library, book, and series pages.
				</p>
			{:else}
				<ul class="divide-y divide-border rounded-lg border border-border bg-card">
					{#each list as rule (rule.id)}
						<li class="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
							<span class="min-w-0 truncate">
								<span class="text-muted-foreground">{SCOPE_LABEL[rule.scope]}:</span>
								{rule.label ?? `#${rule.entity_id}`}
								<span class="ml-1 rounded px-1.5 py-0.5 text-xs font-medium {rule.mode === 'include' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}">
									{rule.mode}
								</span>
							</span>
							<button
								type="button"
								onclick={() => removeRule(rule.id)}
								aria-label="Remove rule"
								class="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
							>
								<X class="h-4 w-4" />
							</button>
						</li>
					{/each}
				</ul>
			{/if}

			{#snippet pending()}
				<div class="h-16 animate-pulse rounded-lg border border-border bg-card"></div>
			{/snippet}
		</svelte:boundary>
	</div>
</div>
