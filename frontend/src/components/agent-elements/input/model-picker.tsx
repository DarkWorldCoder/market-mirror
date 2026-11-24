import * as React from "react";
import { memo, useEffect, useRef, useState } from "react";
import { IconCheck, IconChevronDown, IconPlus, IconSearch } from "@tabler/icons-react";
import { Popover } from "@base-ui/react/popover";
import type { ModelOption } from "../types";
import { cn } from "../utils/cn";
import { claudeLoginFallback, modelStatus, rejectedModel } from "./model-status.js";

export type ModelPickerProps = {
  models: ModelOption[]; value?: string; defaultValue?: string;
  onChange?: (modelId: string) => void; onAddModel?: () => void;
  placeholder?: string; className?: string; disabled?: boolean;
};
export const ModelPicker = memo(function ModelPicker({models,value,defaultValue,onChange,onAddModel,placeholder="Choose a model",className,disabled=false}: ModelPickerProps) {
  const [internalValue,setInternalValue] = useState(defaultValue);
  const activeId = value !== undefined ? value : internalValue;
  const activeModel = models.find(m=>m.id===activeId && m.available!==false) ?? models.find(m=>m.available!==false);
  const [open,setOpen] = useState(false), [query,setQuery] = useState(''), [theme,setTheme] = useState('light');
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(()=>{if(disabled)setOpen(false)},[disabled]);
  const groups = new Map<string,ModelOption[]>();
  for(const model of models.filter(m=>`${m.name} ${m.provider||''} ${m.description||''}`.toLowerCase().includes(query.trim().toLowerCase()))) {
    const group = model.provider || 'Available models';
    groups.set(group,[...(groups.get(group)||[]),model]);
  }
  const rejected = rejectedModel(models), fallback = rejected ? claudeLoginFallback(models) : null;
  const rejectedName = rejected ? ({claude:'Anthropic',openai:'OpenAI',gemini:'Google Gemini',openrouter:'OpenRouter'} as Record<string,string>)[rejected.provider||''] || rejected.provider || 'provider' : '';
  function choose(id:string) { if(disabled)return; if(value===undefined)setInternalValue(id); onChange?.(id); setOpen(false); }
  function navigate(event:React.KeyboardEvent<HTMLElement>) {
    if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
    const items=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('.library-model-fallback, [role="menuitemradio"], .library-model-add'));
    const current=items.indexOf(document.activeElement as HTMLButtonElement);
    const next=event.key==='ArrowDown'?(current+1)%items.length:event.key==='ArrowUp'?(current-1+items.length)%items.length:event.key==='Home'?0:items.length-1;
    if(items.length){event.preventDefault();items[next]?.focus();}
  }
  return <Popover.Root open={open} onOpenChange={next=>{setTheme(trigger.current?.closest('[data-theme]')?.getAttribute('data-theme')||'light');setOpen(next);if(next)setQuery('');}}>
    <Popover.Trigger ref={trigger} type="button" disabled={disabled} aria-label="Select model" className={cn('an-model-trigger library-model-trigger',className)}><span>{activeModel?.name||placeholder}</span><IconChevronDown size={12} aria-hidden="true" /></Popover.Trigger>
    <Popover.Portal><Popover.Positioner side="top" align="start" sideOffset={10} collisionPadding={12} className="library-context-positioner">
      <Popover.Popup className="library-context-popup library-model-popup an-model-popup" data-theme={theme} aria-label="Choose a model" onKeyDown={navigate}>
        <label className="library-model-search"><IconSearch size={16} aria-hidden="true" /><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search models…" aria-label="Search models" /></label>
        {rejected&&<div className="library-model-alert" role="status"><p>Your {rejectedName} key was rejected.</p>{fallback&&<button type="button" className="library-model-fallback" onClick={()=>choose(fallback.id)}>Use my Claude Code login</button>}</div>}
        <div role="menu" aria-label="Available models" className="library-model-list">
          {[...groups].map(([provider,options])=><section key={provider} role="group" aria-label={provider}><p className="library-model-group">{provider}</p>{options.map(model=>{const status=modelStatus(model);const active=model.id===activeModel?.id;return <button key={model.id} type="button" role="menuitemradio" aria-checked={active} className="an-model-option library-model-option" data-status={status.id} onClick={()=>choose(model.id)}><span><b>{model.name}{model.version&&` ${model.version}`}</b>{model.description&&<small>{model.description}</small>}</span><span className="library-model-side"><span className="library-model-connect library-model-status" data-tone={status.tone}>{status.label}</span>{active&&<IconCheck size={17} aria-label="Selected" />}</span></button>})}</section>)}
          {!groups.size&&<p className="library-model-empty">No matching models.</p>}
        </div>
        {onAddModel&&<button type="button" className="library-model-add" onClick={()=>{setOpen(false);onAddModel();}}><IconPlus size={17} aria-hidden="true" />Add or configure models</button>}
      </Popover.Popup>
    </Popover.Positioner></Popover.Portal>
  </Popover.Root>;
});

export type ModelBadgeProps = {
  models: ModelOption[];
  value?: string;
  placeholder?: string;
  className?: string;
};

export const ModelBadge = memo(function ModelBadge({
  models,
  value,
  placeholder = "Auto",
  className,
}: ModelBadgeProps) {
  const activeModel = models.find((m) => m.id === value) ?? models[0];
  return (
    <div
      className={cn(
        "inline-flex h-7 items-center px-2 text-[12px] leading-4 text-foreground/30",
        className,
      )}
    >
      <span className="font-medium">{activeModel?.name ?? placeholder}</span>
      {activeModel?.version && (
        <span className="ml-0.5 font-normal text-foreground/20">
          {activeModel.version}
        </span>
      )}
    </div>
  );
});
