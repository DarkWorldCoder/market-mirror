# Agent Elements registry components

Installed from the official 21st.dev registry with the shadcn CLI on 23 November 2026:

```text
npx shadcn@latest add https://agent-elements.21st.dev/r/input-bar.json
npx shadcn@latest add https://agent-elements.21st.dev/r/model-picker.json
```

Official documentation: https://agent-elements.21st.dev/docs/input-bar and https://agent-elements.21st.dev/docs/model-picker

The CLI generated `input-bar.tsx`, its `input/`, `question/`, `utils/` dependencies, `image-lightbox.tsx`, and `agent-ui.css`. These are actual registry components, kept as editable source. The Vue host mounts `ComposerIsland.tsx` through `LibraryComposer.vue`.

Local adaptations:

- Server-component directives are omitted because this host is a client-only Vite app.
- Explicit React namespace imports support the existing Vite JSX transform without converting the Vue app.
- A local `ChatStatus` type preserves the four-state input contract without installing an unused AI SDK runtime.
- Send/stop uses a native, named button so keyboard and assistive-technology users can activate it. The textarea has an accessible name. IME composition does not send a partial message.
- Theme defaults are scoped to `.library-composer`; the host maps them onto its existing light/dark workspace tokens.
- The official ModelPicker and its Base UI Popover are installed from the registry. The host supplies available models and handles model switching. Provider details are shown when supplied. The popover uses its native button trigger and stays inside the local theme container.
- Input spacing and control sizes are adapted to the workspace. Attachment and connector actions emit events to the Vue host; the host owns file selection and connector setup. The component does not invent microphone, image-generation, or upload behavior.

`ComposerIsland.tsx`, `types.ts`, and the Vue wrapper are local integration code; the other source files originate from the registry listed above.
