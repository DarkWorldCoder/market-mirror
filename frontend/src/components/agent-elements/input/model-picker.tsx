import * as React from "react";
import { memo, useEffect, useRef, useState } from "react";
import { IconCheck, IconChevronDown, IconPlus, IconSearch } from "@tabler/icons-react";
import { Popover } from "@base-ui/react/popover";
import type { ModelOption } from "../types";
import { cn } from "../utils/cn";

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
  function choose(id:string) { if(disabled)return; if(value===undefined)setInternalValue(id); onChange?.(id); setOpen(false); }
  function navigate(event:React.KeyboardEvent<HTMLElement>) {
    if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
    const items=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"], .library-model-add'));
    const current=items.indexOf(document.activeElement as HTMLButtonElement);
    const next=event.key==='ArrowDown'?(current+1)%items.length:event.key==='ArrowUp'?(current-1+items.length)%items.length:event.key==='Home'?0:items.length-1;
    if(items.length){event.preventDefault();items[next]?.focus();}
  }
  return <Popover.Root open={open} onOpenChange={next=>{setTheme(trigger.current?.closest('[data-theme]')?.getAttribute('data-theme')||'light');setOpen(next);if(next)setQuery('');}}>
    <Popover.Trigger ref={trigger} type="button" disabled={disabled} aria-label="Select model" className={cn('an-model-trigger library-model-trigger',className)}><span>{activeModel?.name||placeholder}</span><IconChevronDown size={12} aria-hidden="true" /></Popover.Trigger>
    <Popover.Portal><Popover.Positioner side="top" align="start" sideOffset={10} collisionPadding={12} className="library-context-positioner">
      <Popover.Popup className="library-context-popup library-model-popup an-model-popup" data-theme={theme} aria-label="Choose a model" onKeyDown={navigate}>
        <label className="library-model-search"><IconSearch size={16} aria-hidden="true" /><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search models…" aria-label="Search models" /></label>
        <div role="menu" aria-label="Available models" className="library-model-list">
          {[...groups].map(([provider,options])=><section key={provider} role="group" aria-label={provider}><p className="library-model-group">{provider}</p>{options.map(model=><button key={model.id} type="button" role="menuitemradio" aria-checked={model.id===activeModel?.id} className="an-model-option library-model-option" onClick={()=>choose(model.id)}><span><b>{model.name}{model.version&&` ${model.version}`}</b>{model.description&&<small>{model.description}</small>}</span>{model.available===false?<span className="library-model-connect">Connect</span>:model.id===activeModel?.id&&<IconCheck size={17} aria-hidden="true" />}</button>)}</section>)}
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
