<script lang="ts">
  export let warning_message: string | undefined | null = undefined
  export let warning_color: "error" | "warning" = "error"
  export let tight: boolean = false
  export let trusted: boolean = false

  function html_warning_message() {
    let message = warning_message
    if (!message) {
      return ""
    }
    message = message.replace(
      /https?:\/\/\S+/g,
      '<a href="$&" class="link underline" target="_blank">$&</a>',
    )
    const paragraphs = message.split("\n")
    return paragraphs
      .map((paragraph: string) => {
        return `<p>${paragraph}</p>`
      })
      .join("")
  }
</script>

{#if warning_message}
  <div class="text-sm text-gray-500 flex flex-row items-center mt-2">
    <svg
      class="w-5 h-5 flex-none {warning_color === 'error'
        ? 'text-error'
        : 'text-warning'}"
      fill="currentColor"
      width="800px"
      height="800px"
      viewBox="0 0 256 256"
      id="Flat"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M128,20.00012a108,108,0,1,0,108,108A108.12217,108.12217,0,0,0,128,20.00012Zm0,192a84,84,0,1,1,84-84A84.0953,84.0953,0,0,1,128,212.00012Zm-12-80v-52a12,12,0,1,1,24,0v52a12,12,0,1,1-24,0Zm28,40a16,16,0,1,1-16-16A16.018,16.018,0,0,1,144,172.00012Z"
      />
    </svg>

    <div class="{tight ? 'pl-1' : 'pl-4'} flex flex-col gap-2">
      {#if trusted}
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        {@html html_warning_message()}
      {:else}
        {warning_message}
      {/if}
    </div>
  </div>
{/if}
