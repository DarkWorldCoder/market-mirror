import * as React from 'react';
import { useEffect, useRef, useState } from 'react';
import { InputBar } from './input-bar';
import { ModelPicker } from './input/model-picker';
import { IconPlugConnected, IconPlus, IconPaperclip, IconFolder, IconCommand, IconSettings, IconWorld } from '@tabler/icons-react';
import { Popover } from '@base-ui/react/popover';
import type { ModelOption } from './types';

type ComposerIslandProps = {
  disabled: boolean;
  busy: boolean;
  placeholder: string;
  value?: string;
  revision: number;
  models: ModelOption[];
  selectedModel: string;
  changing: boolean;
  onModelChange: (id: string) => void;
  onAttach: () => void;
  onConnectors: () => void;
  onChooseRun: () => void;
  onSkills: () => void;
  onSettings: () => void;
  onBrowser: () => void;
  onChange: (value: string) => void;
  onSend: (content: string) => void;
  onStop: () => void;
};

/** Small React boundary around the registry component; Vue owns requests and conversation state. */
export function ComposerIsland(props: ComposerIslandProps) {
  const [draft, setDraft] = useState(props.value ?? '');
  useEffect(() => {
    if (props.value !== undefined) setDraft(props.value);
  }, [props.value, props.revision]);
  return (
    <InputBar
      className="library-composer-input"
      value={draft}
      onChange={(value) => { setDraft(value); props.onChange(value); }}
      placeholder={props.placeholder}
      disabled={props.disabled}
      status={props.busy ? 'streaming' : 'ready'}
      onSend={({ content }) => {
        if (props.disabled || props.busy || !content.trim()) return;
        setDraft('');
        props.onChange('');
        props.onSend(content.trim());
      }}
      onStop={props.onStop}
      leftActions={
        <>
          <ContextMenu disabled={props.busy} onAttach={props.onAttach} onChooseRun={props.onChooseRun} onConnectors={props.onConnectors} onSkills={props.onSkills} onSettings={props.onSettings} onBrowser={props.onBrowser} />
          <ModelPicker
            models={props.models}
            value={props.selectedModel}
            onChange={props.onModelChange}
            onAddModel={props.onSettings}
            disabled={props.busy || props.changing}
            placeholder={props.changing ? 'Changing model…' : 'Choose a model'}
          />

        </>
      }
    />
  );
}


type ContextMenuProps = Pick<ComposerIslandProps, 'onAttach' | 'onChooseRun' | 'onConnectors' | 'onSkills' | 'onSettings' | 'onBrowser'> & { disabled: boolean };
function ContextMenu(props: ContextMenuProps) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState('light');
  const trigger = useRef<HTMLButtonElement>(null);
  const items = [
    { label: 'Upload files', detail: 'Documents, CSV and research', icon: IconPaperclip, action: props.onAttach },
    { label: 'View a website', detail: 'Open a page for analysis', icon: IconWorld, action: props.onBrowser },
    { label: 'Saved runs', detail: 'Reports and experiment context', icon: IconFolder, action: props.onChooseRun },
    { label: 'Connectors', detail: 'Analytics, ads and model providers', icon: IconPlugConnected, action: props.onConnectors },
    { label: 'Skills', detail: 'Explore every available tool', icon: IconCommand, action: props.onSkills },
    { label: 'Settings', detail: 'Models, memory and preferences', icon: IconSettings, action: props.onSettings },
  ];
  function navigate(event: React.KeyboardEvent<HTMLElement>) {
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === 'ArrowDown' ? (current + 1) % buttons.length : event.key === 'ArrowUp' ? (current - 1 + buttons.length) % buttons.length : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : -1;
    if (next >= 0) { event.preventDefault(); buttons[next]?.focus(); }
  }
  return <Popover.Root open={open} onOpenChange={next => { setTheme(trigger.current?.closest('[data-theme]')?.getAttribute('data-theme') || 'light'); setOpen(next); }}>
    <Popover.Trigger ref={trigger} className="library-add-trigger" disabled={props.disabled} aria-label="Add files, context or tools" title="Add files, context or tools"><IconPlus size={19} aria-hidden="true" /></Popover.Trigger>
    <Popover.Portal>
      <Popover.Positioner side="top" align="start" sideOffset={10} className="library-context-positioner">
        <Popover.Popup className="library-context-popup" data-theme={theme} aria-label="Add to conversation">
          <div role="menu" aria-label="Conversation tools" onKeyDown={navigate}>
            {items.map(({ label, detail, icon: Icon, action }) => <button key={label} type="button" role="menuitem" className="library-context-item" onClick={() => { setOpen(false); action(); }}><Icon size={19} aria-hidden="true" /><span><b>{label}</b><small>{detail}</small></span></button>)}
          </div>
        </Popover.Popup>
      </Popover.Positioner>
    </Popover.Portal>
  </Popover.Root>;
}
