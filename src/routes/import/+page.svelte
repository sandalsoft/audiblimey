<script lang="ts">
	import {
		uploadGoodreads,
		startAudibleSync,
		getSyncStatus,
		getImportStats,
		getImportHistory,
		type UploadGoodreadsResponse,
		type SyncStatusResponse,
		type SyncJobStatus
	} from '$lib/api/import.remote';
	import {
		getAudibleAuthStatus,
		startAudibleAuth,
		completeAudibleAuth
	} from '$lib/api/auth.remote';

	const stats = $derived(await getImportStats());
	const historyData = $derived(await getImportHistory());
	const authStatusQuery = getAudibleAuthStatus();
	const authStatus = $derived(await authStatusQuery);

	// --- Goodreads upload state ---
	let selectedFile = $state<File | null>(null);
	let isUploading = $state(false);
	let uploadResult = $state<UploadGoodreadsResponse | null>(null);
	let uploadError = $state<string | null>(null);

	// --- Audible sync state ---
	let isSyncing = $state(false);
	let syncStarted = $state(false);
	let syncError = $state<string | null>(null);
	let syncStatus = $state<SyncStatusResponse | null>(null);
	let isRefreshingStatus = $state(false);

	// --- Audible auth state ---
	let isStartingAuth = $state(false);
	let oauthUrl = $state<string | null>(null);
	let authSessionId = $state<string | null>(null);
	let responseUrl = $state('');
	let isCompletingAuth = $state(false);
	let authError = $state<string | null>(null);

	async function handleStartAuth() {
		isStartingAuth = true;
		authError = null;
		oauthUrl = null;
		try {
			const result = await startAudibleAuth();
			oauthUrl = result.oauth_url;
			authSessionId = result.session_id;
		} catch (err) {
			authError = err instanceof Error ? err.message : 'Failed to start auth';
		} finally {
			isStartingAuth = false;
		}
	}

	async function handleCompleteAuth() {
		if (!authSessionId || !responseUrl.trim()) return;
		isCompletingAuth = true;
		authError = null;
		try {
			await completeAudibleAuth({
				session_id: authSessionId,
				response_url: responseUrl.trim(),
			}).updates(authStatusQuery);
			// Reset auth flow UI
			oauthUrl = null;
			authSessionId = null;
			responseUrl = '';
		} catch (err) {
			authError = err instanceof Error ? err.message : 'Auth failed';
		} finally {
			isCompletingAuth = false;
		}
	}

	function handleFileSelect(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		selectedFile = input.files?.[0] ?? null;
		uploadResult = null;
		uploadError = null;
	}

	async function handleUpload() {
		if (!selectedFile) return;
		isUploading = true;
		uploadError = null;
		uploadResult = null;

		try {
			uploadResult = await uploadGoodreads(selectedFile);
		} catch (err) {
			uploadError = err instanceof Error ? err.message : 'Upload failed';
		} finally {
			isUploading = false;
		}
	}

	async function handleSync() {
		isSyncing = true;
		syncError = null;

		try {
			await startAudibleSync();
			syncStarted = true;
			await refreshSyncStatus();
		} catch (err) {
			const msg = err instanceof Error ? err.message : 'Sync failed';
			if (msg.includes('400')) {
				syncError = 'No Audible account configured. Set up your Audible credentials first.';
			} else if (msg.includes('409')) {
				syncError = 'A sync is already running. Wait for it to finish.';
			} else {
				syncError = msg;
			}
		} finally {
			isSyncing = false;
		}
	}

	async function refreshSyncStatus() {
		isRefreshingStatus = true;
		try {
			syncStatus = await getSyncStatus();
		} catch {
			// silently fail — status panel just stays stale
		} finally {
			isRefreshingStatus = false;
		}
	}

	function isSyncJob(s: SyncStatusResponse): s is SyncJobStatus {
		return s.status !== 'no_syncs';
	}

	function formatStatusBadge(status: string): { label: string; classes: string } {
		switch (status) {
			case 'completed':
				return { label: 'Completed', classes: 'bg-green-500/10 text-green-600 dark:text-green-400' };
			case 'running':
				return { label: 'Running', classes: 'bg-blue-500/10 text-blue-600 dark:text-blue-400' };
			case 'pending':
				return { label: 'Pending', classes: 'bg-yellow-500/10 text-yellow-600 dark:text-yellow-400' };
			case 'failed':
				return { label: 'Failed', classes: 'bg-destructive/10 text-destructive' };
			default:
				return { label: status, classes: 'bg-muted text-muted-foreground' };
		}
	}

	function formatDate(dateStr: string | null): string {
		if (!dateStr) return '—';
		return new Date(dateStr).toLocaleString();
	}
</script>

<h1 class="font-heading text-3xl font-bold text-foreground">Import & Sync</h1>
<p class="mt-2 text-muted-foreground">
	Import your Goodreads library or sync your Audible collection.
</p>

<div class="mt-8 grid gap-6 lg:grid-cols-2">
	<!-- Goodreads CSV Upload Card -->
	<div class="rounded-xl border border-border bg-card p-6">
		<h2 class="font-heading text-lg font-semibold text-card-foreground">Goodreads Import</h2>
		<p class="mt-1 text-sm text-muted-foreground">
			Upload your Goodreads CSV export to import ratings and shelves.
		</p>

		<div class="mt-4 space-y-4">
			<div>
				<label for="csv-upload" class="block text-sm font-medium text-card-foreground">
					CSV File
				</label>
				<input
					id="csv-upload"
					type="file"
					accept=".csv"
					onchange={handleFileSelect}
					class="mt-1 block w-full text-sm text-muted-foreground file:mr-3 file:rounded-lg file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
				/>
			</div>

			<button
				onclick={handleUpload}
				disabled={!selectedFile || isUploading}
				class="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
			>
				{isUploading ? 'Uploading…' : 'Upload & Import'}
			</button>

			{#if uploadError}
				<div class="rounded-lg border border-destructive/50 bg-destructive/10 p-4">
					<p class="text-sm text-destructive">{uploadError}</p>
				</div>
			{/if}

			{#if uploadResult}
				<div class="rounded-lg border border-border bg-accent/50 p-4">
					<p class="text-sm font-medium text-card-foreground">Import complete</p>
					<div class="mt-3 grid grid-cols-2 gap-3 text-sm">
						<div>
							<span class="text-muted-foreground">Total books</span>
							<p class="font-semibold text-card-foreground">{uploadResult.import.total_books}</p>
						</div>
						<div>
							<span class="text-muted-foreground">Inserted</span>
							<p class="font-semibold text-card-foreground">{uploadResult.import.inserted}</p>
						</div>
						<div>
							<span class="text-muted-foreground">Matched</span>
							<p class="font-semibold text-card-foreground">
								{uploadResult.matching.total_attempted - uploadResult.matching.unmatched}
							</p>
						</div>
						<div>
							<span class="text-muted-foreground">Match rate</span>
							<p class="font-semibold text-card-foreground">
								{Math.round(uploadResult.matching.match_rate * 100)}%
							</p>
						</div>
					</div>
				</div>
			{/if}
		</div>
	</div>

	<!-- Audible Sync Card -->
	<div class="rounded-xl border border-border bg-card p-6">
		<h2 class="font-heading text-lg font-semibold text-card-foreground">Audible Sync</h2>
		<p class="mt-1 text-sm text-muted-foreground">
			Link your Audible account and sync your library.
		</p>

		<div class="mt-4 space-y-4">
			<!-- Account Status -->
			<svelte:boundary>
				{#if authStatus.linked}
					<div class="flex items-center gap-2 rounded-lg border border-border bg-accent/50 px-4 py-3">
						<span class="inline-block h-2.5 w-2.5 rounded-full bg-green-500"></span>
						<span class="text-sm font-medium text-card-foreground">Audible account linked</span>
						<span class="text-xs text-muted-foreground">({authStatus.marketplace})</span>
					</div>
				{:else if oauthUrl}
					<!-- Step 2: User needs to log in and paste URL -->
					<div class="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-3">
						<p class="text-sm font-medium text-card-foreground">Step 1: Log in to Amazon</p>
						<p class="text-xs text-muted-foreground">
							Open this link, sign in with your Amazon credentials, then copy the URL from the "page not found" page.
						</p>
						<a
							href={oauthUrl}
							target="_blank"
							rel="noopener noreferrer"
							class="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
						>
							Open Amazon Login ↗
						</a>

						<div class="border-t border-border pt-3">
							<p class="text-sm font-medium text-card-foreground">Step 2: Paste the redirect URL</p>
							<p class="text-xs text-muted-foreground">
								After logging in, your browser will show a "page not found" error. Copy the full URL from the address bar and paste it here.
							</p>
							<input
								type="text"
								placeholder="https://localhost/…"
								bind:value={responseUrl}
								class="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
							/>
							<button
								onclick={handleCompleteAuth}
								disabled={isCompletingAuth || !responseUrl.trim()}
								class="mt-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
							>
								{isCompletingAuth ? 'Linking…' : 'Complete Linking'}
							</button>
						</div>
					</div>
				{:else}
					<button
						onclick={handleStartAuth}
						disabled={isStartingAuth}
						class="rounded-lg border border-border bg-card px-4 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
					>
						{isStartingAuth ? 'Generating link…' : 'Link Audible Account'}
					</button>
				{/if}

				{#if authError}
					<div class="rounded-lg border border-destructive/50 bg-destructive/10 p-3">
						<p class="text-sm text-destructive">{authError}</p>
					</div>
				{/if}

				{#snippet pending()}
					<div class="flex items-center gap-2 animate-pulse">
						<div class="h-2.5 w-2.5 rounded-full bg-muted"></div>
						<div class="h-4 w-40 rounded bg-muted"></div>
					</div>
				{/snippet}
				{#snippet failed(error, reset)}
					<div class="text-sm text-muted-foreground">
						Could not check account status.
						<button onclick={reset} class="text-primary underline-offset-4 hover:underline">Retry</button>
					</div>
				{/snippet}
			</svelte:boundary>

			<!-- Sync Controls (only when linked) -->
			{#if authStatus.linked}
			<div class="border-t border-border pt-4">
			<div class="flex items-center gap-3">
				<button
					onclick={handleSync}
					disabled={isSyncing}
					class="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
				>
					{isSyncing ? 'Starting sync…' : 'Sync Library'}
				</button>

				{#if syncStarted || syncStatus}
					<button
						onclick={refreshSyncStatus}
						disabled={isRefreshingStatus}
						class="rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
					>
						{isRefreshingStatus ? 'Refreshing…' : 'Refresh Status'}
					</button>
				{/if}
			</div>

			{#if syncError}
				<div class="rounded-lg border border-destructive/50 bg-destructive/10 p-4">
					<p class="text-sm text-destructive">{syncError}</p>
				</div>
			{/if}

			{#if syncStatus}
				{#if isSyncJob(syncStatus)}
					{@const badge = formatStatusBadge(syncStatus.status)}
					<div class="rounded-lg border border-border bg-accent/50 p-4">
						<div class="flex items-center gap-2">
							<span class="inline-flex rounded-md px-2 py-0.5 text-xs font-medium {badge.classes}">
								{badge.label}
							</span>
							<span class="text-xs text-muted-foreground">Job #{syncStatus.job_id}</span>
						</div>

						<div class="mt-3 grid grid-cols-3 gap-3 text-sm">
							<div>
								<span class="text-muted-foreground">Processed</span>
								<p class="font-semibold text-card-foreground">{syncStatus.books_processed ?? '—'}</p>
							</div>
							<div>
								<span class="text-muted-foreground">Added</span>
								<p class="font-semibold text-card-foreground">{syncStatus.books_added ?? '—'}</p>
							</div>
							<div>
								<span class="text-muted-foreground">Updated</span>
								<p class="font-semibold text-card-foreground">{syncStatus.books_updated ?? '—'}</p>
							</div>
						</div>

						<div class="mt-3 text-xs text-muted-foreground">
							<p>Started: {formatDate(syncStatus.started_at)}</p>
							{#if syncStatus.completed_at}
								<p>Completed: {formatDate(syncStatus.completed_at)}</p>
							{/if}
						</div>

						{#if syncStatus.error_message}
							<div class="mt-3 rounded-md bg-destructive/10 p-2">
								<p class="text-xs text-destructive">{syncStatus.error_message}</p>
							</div>
						{/if}
					</div>
				{:else}
					<p class="text-sm text-muted-foreground">No sync history yet.</p>
				{/if}
			{/if}
		</div>
		{/if}
	</div>
</div>
</div>

<!-- Import Stats Dashboard -->
<section class="mt-10">
	<h2 class="font-heading text-xl font-semibold text-foreground">Import Statistics</h2>

	<svelte:boundary>
		<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
			<div class="rounded-xl border border-border bg-card p-5">
				<p class="text-sm text-muted-foreground">Goodreads Books</p>
				<p class="mt-1 font-heading text-2xl font-bold text-card-foreground">{stats.total_goodreads_books}</p>
			</div>
			<div class="rounded-xl border border-border bg-card p-5">
				<p class="text-sm text-muted-foreground">Matched</p>
				<p class="mt-1 font-heading text-2xl font-bold text-card-foreground">{stats.total_matched}</p>
			</div>
			<div class="rounded-xl border border-border bg-card p-5">
				<p class="text-sm text-muted-foreground">Unmatched</p>
				<p class="mt-1 font-heading text-2xl font-bold text-card-foreground">{stats.total_unmatched}</p>
			</div>
			<div class="rounded-xl border border-border bg-card p-5">
				<p class="text-sm text-muted-foreground">Match Rate</p>
				<p class="mt-1 font-heading text-2xl font-bold text-card-foreground">
					{Math.round(stats.match_rate * 100)}%
				</p>
			</div>
		</div>

		<!-- Rating Distribution -->
		{#if Object.keys(stats.rating_distribution).length > 0}
			<div class="mt-6 rounded-xl border border-border bg-card p-6">
				<h3 class="font-heading text-base font-semibold text-card-foreground">Rating Distribution</h3>
				<div class="mt-4 space-y-3">
					{#each Object.entries(stats.rating_distribution).sort(([a], [b]) => Number(b) - Number(a)) as [rating, count]}
						{@const maxCount = Math.max(...Object.values(stats.rating_distribution))}
						{@const pct = maxCount > 0 ? (count / maxCount) * 100 : 0}
						<div class="flex items-center gap-3">
							<span class="w-16 text-sm text-muted-foreground">{rating} star{rating !== '1' ? 's' : ''}</span>
							<div class="flex-1">
								<div class="h-5 rounded-md bg-muted">
									<div
										class="h-5 rounded-md bg-primary transition-all"
										style="width: {pct}%"
									></div>
								</div>
							</div>
							<span class="w-10 text-right text-sm font-medium text-card-foreground">{count}</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Match Sources Breakdown -->
		{#if Object.keys(stats.match_sources).length > 0}
			<div class="mt-6 rounded-xl border border-border bg-card p-6">
				<h3 class="font-heading text-base font-semibold text-card-foreground">Match Sources</h3>
				<div class="mt-4 grid gap-3 sm:grid-cols-3">
					{#each Object.entries(stats.match_sources) as [source, count]}
						<div class="rounded-lg bg-accent/50 p-3 text-center">
							<p class="text-sm text-muted-foreground">
								{source.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
							</p>
							<p class="mt-1 font-heading text-xl font-bold text-card-foreground">{count}</p>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Top Shelves -->
		{#if Object.keys(stats.top_shelves).length > 0}
			<div class="mt-6 rounded-xl border border-border bg-card p-6">
				<h3 class="font-heading text-base font-semibold text-card-foreground">Top Shelves</h3>
				<div class="mt-4 flex flex-wrap gap-2">
					{#each Object.entries(stats.top_shelves).sort(([, a], [, b]) => b - a).slice(0, 15) as [shelf, count]}
						<span class="inline-flex items-center gap-1.5 rounded-full border border-border bg-accent/50 px-3 py-1 text-sm">
							<span class="text-card-foreground">{shelf}</span>
							<span class="text-xs text-muted-foreground">({count})</span>
						</span>
					{/each}
				</div>
			</div>
		{/if}

		{#snippet pending()}
			<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
				{#each { length: 4 } as _}
					<div class="animate-pulse rounded-xl border border-border bg-card p-5">
						<div class="h-4 w-2/3 rounded bg-muted"></div>
						<div class="mt-3 h-8 w-1/2 rounded bg-muted"></div>
					</div>
				{/each}
			</div>
		{/snippet}

		{#snippet failed(error, reset)}
			<div class="mt-4 rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
				<p class="font-heading text-lg text-destructive">Failed to load import stats</p>
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
</section>

<!-- Import History -->
<section class="mt-10">
	<h2 class="font-heading text-xl font-semibold text-foreground">Import History</h2>

	<svelte:boundary>
		{#if historyData.imports.length === 0}
			<div class="mt-4 rounded-xl border border-border bg-card p-10 text-center">
				<p class="font-heading text-lg text-card-foreground">No imports yet</p>
				<p class="mt-2 text-sm text-muted-foreground">
					Upload a Goodreads CSV or sync your Audible library to get started.
				</p>
			</div>
		{:else}
			<div class="mt-4 overflow-x-auto rounded-xl border border-border bg-card">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-border text-left">
							<th class="px-4 py-3 font-medium text-muted-foreground">Type</th>
							<th class="px-4 py-3 font-medium text-muted-foreground">Total Rows</th>
							<th class="px-4 py-3 font-medium text-muted-foreground">Matched</th>
							<th class="px-4 py-3 font-medium text-muted-foreground">Match Rate</th>
							<th class="px-4 py-3 font-medium text-muted-foreground">Status</th>
							<th class="px-4 py-3 font-medium text-muted-foreground">Date</th>
						</tr>
					</thead>
					<tbody>
						{#each historyData.imports as job (job.id)}
							{@const badge = formatStatusBadge(job.status)}
							<tr class="border-b border-border last:border-0">
								<td class="px-4 py-3 font-medium text-card-foreground capitalize">{job.type}</td>
								<td class="px-4 py-3 text-card-foreground">{job.total_rows ?? '—'}</td>
								<td class="px-4 py-3 text-card-foreground">{job.matched ?? '—'}</td>
								<td class="px-4 py-3 text-card-foreground">{Math.round(job.match_rate * 100)}%</td>
								<td class="px-4 py-3">
									<span class="inline-flex rounded-md px-2 py-0.5 text-xs font-medium {badge.classes}">
										{badge.label}
									</span>
								</td>
								<td class="px-4 py-3 text-muted-foreground">{formatDate(job.started_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		{#snippet pending()}
			<div class="mt-4 animate-pulse rounded-xl border border-border bg-card p-6">
				<div class="space-y-3">
					{#each { length: 3 } as _}
						<div class="h-8 w-full rounded bg-muted"></div>
					{/each}
				</div>
			</div>
		{/snippet}

		{#snippet failed(error, reset)}
			<div class="mt-4 rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
				<p class="font-heading text-lg text-destructive">Failed to load import history</p>
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
</section>
