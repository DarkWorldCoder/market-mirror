"""Bounded Playwright control for persona journeys; no model-supplied scripts/selectors.

Each observation binds opaque references to actual observed elements. If the
page replaces one, the caller must re-observe instead of clicking a new node
that happens to occupy the same index. Playwright stays on its owning thread.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

ACTIONS = ("click", "fill", "select", "check", "press", "hover", "focus", "scroll", "wait", "back", "forward", "reload", "navigate", "switch_tab", "close_tab", "leave", "finish")


class PolicyBlocked(ValueError):
    """An action exceeds the configured website test's permissions."""


class StaleTarget(ValueError):
    """The observed target changed; acquire a fresh observation."""


CONTROL_SNAPSHOT = r"""({prefix,limit}) => {
 const roots=[document];for(let i=0;i<roots.length&&roots.length<25;i++){for(const e of [...roots[i].querySelectorAll('*')].slice(0,10000)){if(e.shadowRoot&&!roots.includes(e.shadowRoot))roots.push(e.shadowRoot);if(roots.length>=25)break;}}
 roots.forEach(root=>root.querySelectorAll('[data-marketmirror-id]').forEach(e=>e.removeAttribute('data-marketmirror-id')));
 const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&s.opacity!=='0'&&r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth;};
 const labelText=e=>{const node=e.labels?.[0];if(!node)return '';const copy=node.cloneNode(true);copy.querySelectorAll('input,select,textarea,button').forEach(x=>x.remove());return copy.textContent.trim();};
 const label=e=>{const ids=(e.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean);
   return (e.getAttribute('aria-label')||ids.map(id=>document.getElementById(id)?.innerText||'').join(' ').trim()||labelText(e)||
   ((!e.isContentEditable&&e.tagName!=='INPUT'&&e.tagName!=='TEXTAREA')?e.innerText:'')||e.getAttribute('placeholder')||e.getAttribute('alt')||e.getAttribute('title')||e.name||'').trim().slice(0,180);};
 const controls=roots.flatMap(root=>[...root.querySelectorAll('a[href],button,summary,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=tab],[role=checkbox],[role=radio],[role=switch],[role=combobox],[role=option],[role=menuitem],[role=textbox],[role=searchbox],[contenteditable=true]')])
 .filter(visible).slice(0,limit).map((e,i)=>{const id=prefix+'-e'+i;e.setAttribute('data-marketmirror-id',id);const r=e.getBoundingClientRect();
 return {id,tag:e.tagName.toLowerCase(),type:e.type||e.getAttribute('type')||'',role:e.getAttribute('role')||'',label:label(e),
 href:e.tagName==='A'?e.href:null,disabled:!!e.disabled||e.getAttribute('aria-disabled')==='true',read_only:!!e.readOnly,
 checked:e.matches('input[type=checkbox],input[type=radio]')?e.checked:e.getAttribute('aria-checked'),
 has_value:e.matches('input,textarea')?!!e.value:(e.isContentEditable?!!e.textContent.trim():null),
 editable:e.isContentEditable,required:!!e.required,dom_id:e.id||null,test_id:e.getAttribute('data-testid'),multiple:!!e.multiple,
 min:e.getAttribute('min'),max:e.getAttribute('max'),expanded:e.getAttribute('aria-expanded'),selected:e.getAttribute('aria-selected'),
 form_method:e.form?.method||null,form_action:e.form?.action||null,form_fields:e.form?[...e.form.elements].map(x=>x.type).filter(Boolean):[],
 rect:{x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)},
 options:e.tagName==='SELECT'?[...e.options].map(o=>({value:o.value,label:o.text,disabled:o.disabled,selected:o.selected})).slice(0,50):[]};});
 const shadowText=roots.slice(1).flatMap(root=>[...root.querySelectorAll('h1,h2,h3,p,[role=status],[role=alert]')].filter(visible).map(e=>e.innerText||'')).join('\n');
 return {url:location.href,title:document.title,text:((document.body?.innerText||'')+'\n'+shadowText).slice(0,7000),controls};
}"""


def _origin(url):
    p = urlparse(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80)


class BrowserController:
    def __init__(self, context, page, spec, validate_action):
        self.context, self.page, self.spec = context, page, spec
        self.validate_action = validate_action
        self.tabs, self.refs, self.events = {}, {}, []
        self.known_urls = {spec['url']}
        self.observation = None
        self.sequence = 0
        self._tab_counter = 0
        context.on('page', self._register_page)
        self._register_page(page)

    def _event(self, kind, **data):
        self.events.append({'kind': kind, **data})
        self.events[:] = self.events[-150:]

    def _register_page(self, page):
        if page in self.tabs.values():
            return
        if len([p for p in self.tabs.values() if not p.is_closed()]) >= 4:
            self._event('tab_blocked', reason='four-tab limit')
            page.close()
            return
        tab_id = f'tab{self._tab_counter}'
        self._tab_counter += 1
        self.tabs[tab_id] = page
        page.set_default_timeout(5000)
        page.set_default_navigation_timeout(15000)
        page.on('dialog', lambda dialog: (self._event('dialog_dismissed', type=dialog.type, message=dialog.message[:240]), dialog.dismiss()))
        page.on('pageerror', lambda error: self._event('page_error', message=str(error)[:300]))
        page.on('console', lambda message: self._event('console_error', message=message.text[:300]) if message.type == 'error' else None)
        self._event('tab_opened', tab_id=tab_id)

    def tab_id(self, page=None):
        return next((key for key, value in self.tabs.items() if value == (page or self.page)), None)

    def _same_site(self, url):
        return _origin(url) == _origin(self.spec['url'])

    def _sync_tabs(self):
        for page in list(self.context.pages):
            self._register_page(page)
        for key, page in list(self.tabs.items()):
            if not page.is_closed() and page.url not in ('about:blank', '') and not self._same_site(page.url):
                self._event('tab_blocked', tab_id=key, reason='outside tested origin', url=page.url)
                page.close()
        if self.page.is_closed():
            pages = [p for p in self.tabs.values() if not p.is_closed() and self._same_site(p.url)]
            if not pages:
                raise StaleTarget('All eligible browser tabs have closed')
            self.page = pages[-1]

    def frames(self):
        """Only visible, same-origin documents are exposed as action scopes."""
        scopes = []
        viewport = self.page.viewport_size or {'width': 1440, 'height': 1000}
        for frame in self.page.frames:
            if frame.is_detached():
                continue
            if frame != self.page.main_frame:
                if not self._same_site(frame.url):
                    try:
                        inherited = frame.url in ('about:blank', 'about:srcdoc') and self._same_site(frame.evaluate('self.origin'))
                    except Exception:
                        inherited = False
                    if not inherited:
                        continue
                try:
                    box = frame.frame_element().bounding_box()
                    if not box or box['x'] >= viewport['width'] or box['y'] >= viewport['height'] or box['x'] + box['width'] <= 0 or box['y'] + box['height'] <= 0:
                        continue
                except Exception:
                    continue
            scopes.append(frame)
        return scopes[:5]

    def _clear_refs(self):
        for handle, _ in self.refs.values():
            try:
                handle.dispose()
            except Exception:
                pass
        self.refs.clear()

    def observe(self):
        for attempt in range(3):
            try:
                return self._observe()
            except PolicyBlocked:
                raise
            except Exception as error:
                if attempt == 2:
                    raise StaleTarget('The page kept changing while acquiring an observation') from error
                self._event('observation_retry', reason=type(error).__name__)
                self.page.wait_for_timeout(200)

    def _observe(self):
        self._sync_tabs()
        if not self._same_site(self.page.url):
            raise PolicyBlocked('The active page is not on the tested origin')
        self.page.wait_for_timeout(200)
        self._clear_refs()
        self.sequence += 1
        oid = f'o{self.sequence}'
        controls, documents = [], []
        for index, frame in enumerate(self.frames()):
            data = frame.evaluate(CONTROL_SNAPSHOT, {'prefix': f'{oid}-f{index}', 'limit': min(70, 140-len(controls))})
            documents.append({'frame': f'frame{index}', 'url': data['url'], 'text': data['text']})
            for control in data['controls']:
                control['frame'] = f'frame{index}'
                try:
                    handle = frame.locator(f'[data-marketmirror-id="{control["id"]}"]').element_handle(timeout=500)
                except Exception:
                    continue
                if handle:
                    self.refs[control['id']] = (handle, frame)
                    controls.append(control)
                    if control.get('href') and self._same_site(control['href']):
                        self.known_urls.add(control['href'])
            if len(controls) >= 140:
                break
        self.observation = {'observation_id': oid, 'url': self.page.url, 'title': self.page.title(),
            'text': '\n'.join(f'[{d["frame"]}] {d["text"]}' for d in documents)[:10000], 'controls': controls,
            'active_tab': self.tab_id(), 'tabs': [{'id': key, 'url': p.url, 'active': p == self.page,
                'ready': self._same_site(p.url)} for key, p in self.tabs.items() if not p.is_closed()],
            'frames': [{'id': d['frame'], 'url': d['url']} for d in documents],
            'allowed_urls': sorted(self.known_urls)[-150:], 'browser_events': self.events[-8:]}
        return self.observation

    def screenshot(self, path):
        masks = [frame.locator('input,textarea,[contenteditable=true]') for frame in self.page.frames if not frame.is_detached()]
        self.page.screenshot(path=str(path), type='jpeg', quality=60, mask=masks, mask_color='#d6d5ce')

    def _target(self, control, action):
        entry = self.refs.get(control['id'])
        if not entry:
            raise StaleTarget('Target reference is from a different observation')
        handle, frame = entry
        if frame.is_detached() or not handle.evaluate('(e)=>e.isConnected') or not handle.is_visible():
            raise StaleTarget('The page replaced or hid the observed element')
        current = handle.evaluate("(e)=>({tag:e.tagName.toLowerCase(),type:e.type||e.getAttribute('type')||'',href:e.tagName==='A'?e.href:null,aria:e.getAttribute('aria-disabled'),disabled:!!e.disabled,form_fields:e.form?[...e.form.elements].map(x=>x.type).filter(Boolean):[]})")
        if any(current[k] != control.get(k) for k in ('tag', 'type', 'href')) or current['disabled'] or current['aria'] == 'true':
            raise StaleTarget('The observed control changed before execution')
        # Recheck visible text for final/financial actions after async page changes.
        label = handle.evaluate("e=>(e.getAttribute('aria-label')||e.innerText||'').trim().slice(0,180)")
        self.validate_action(action,
            {'controls': [{**control, 'form_fields': current['form_fields'], 'label': label or control['label']}]}, self.spec)
        return handle

    def act(self, action):
        try:
            return self._act(action)
        finally:
            # A reference can be consumed only once. Even a timeout might have
            # submitted a request, so require a new observation before acting.
            self.observation = None

    def _act(self, action):
        if self.observation is None:
            raise StaleTarget('Observe the page before acting')
        if action.get('observation_id') and action['observation_id'] != self.observation['observation_id']:
            raise StaleTarget('Action observation_id is stale')
        control = self.validate_action(action, self.observation, self.spec)
        kind, before = action['action'], self.page.url
        start = time.monotonic()
        target = self._target(control, action) if control else None
        input_matches = None
        if kind == 'back':
            self.page.go_back(wait_until='domcontentloaded')
        elif kind == 'forward':
            self.page.go_forward(wait_until='domcontentloaded')
        elif kind == 'reload':
            self.page.reload(wait_until='domcontentloaded')
        elif kind == 'navigate':
            self.page.goto(action['url'], wait_until='domcontentloaded')
        elif kind == 'switch_tab':
            page = self.tabs.get(action.get('tab_id'))
            if not page or page.is_closed() or not self._same_site(page.url):
                raise StaleTarget('Requested tab is absent, loading, or outside the tested origin')
            self.page = page
        elif kind == 'close_tab':
            others = [p for p in self.tabs.values() if p != self.page and not p.is_closed() and self._same_site(p.url)]
            if not others:
                raise PolicyBlocked('Cannot close the only eligible tab; choose leave to end the journey')
            self.page.close()
            self.page = others[-1]
        elif kind == 'scroll':
            distance = int(action.get('amount') or 600)
            direction = action.get('direction') or 'down'
            self.page.mouse.wheel(distance * (-1 if direction == 'left' else 1) if direction in ('left','right') else 0,
                                  distance * (-1 if direction == 'up' else 1) if direction in ('up','down') else 0)
        elif kind == 'wait':
            self.page.wait_for_timeout(min(2000, max(100, int(action.get('milliseconds') or 700))))
        elif kind == 'click':
            target.click()
        elif kind == 'fill':
            value = self.spec['test_data'][action['test_data_key']] if action.get('test_data_key') else action.get('value','')
            target.fill(str(value)[:1000])
            input_matches = target.evaluate('(e,value)=>(e.isContentEditable?e.textContent:e.value)===value', str(value)[:1000])
        elif kind == 'select':
            selected = next(o for o in control['options'] if action['value'] in (o['value'], o['label']))
            target.select_option(value=selected['value'])
        elif kind == 'check':
            if control['tag'] == 'input':
                target.set_checked(action.get('checked', True))
            elif str(control.get('checked')).lower() != str(action.get('checked', True)).lower():
                target.click()
        elif kind == 'press':
            target.press(action['key'])
        elif kind == 'hover':
            target.hover()
        elif kind == 'focus':
            target.focus()
        self.page.wait_for_timeout(150)
        self._sync_tabs()
        return {'status': 'executed', 'url_before': before, 'url_after': self.page.url,
                'active_tab': self.tab_id(), 'target_label': control.get('label') if control else None,
                'frame': control.get('frame') if control else None,
                'input_matches_requested': input_matches,
                'elapsed_ms': round(1000 * (time.monotonic()-start))}

    def close(self):
        self._clear_refs()
