<script lang="ts">
	import { page } from '$app/state';
	import { cn } from '$lib/utils';
	import { Home, BookOpen, Library, Upload } from 'lucide-svelte';

	const navItems = [
		{ href: '/', label: 'Dashboard', icon: Home },
		{ href: '/library', label: 'Library', icon: BookOpen },
		{ href: '/import', label: 'Import', icon: Upload }
	] as const;
</script>

<aside class="flex h-screen w-60 flex-col border-r border-sidebar-border bg-sidebar">
	<div class="flex items-center gap-2 px-5 py-5">
		<Library class="h-6 w-6 text-primary" />
		<span class="font-heading text-lg font-semibold text-primary">audiblimey</span>
	</div>

	<nav class="flex flex-1 flex-col gap-1 px-3">
		{#each navItems as item}
			{@const active = page.url.pathname === item.href}
			<a
				href={item.href}
				class={cn(
					'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
					active
						? 'bg-sidebar-accent text-primary font-medium'
						: 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-foreground'
				)}
			>
				<item.icon class="h-4 w-4" />
				{item.label}
			</a>
		{/each}
	</nav>

	<div class="border-t border-sidebar-border px-5 py-4">
		<p class="text-xs text-muted-foreground">Audiobook recommendations</p>
	</div>
</aside>
