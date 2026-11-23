<template>
  <component :is="icon" :size="size" :stroke-width="stroke" class="ws-i" aria-hidden="true" focusable="false" />
</template>

<script setup>
// One icon set for the workspace (Lucide, ISC licence), looked up by a short name so data arrays can name icons.
import { computed } from 'vue'
import {
  Activity, ArrowUp, AtSign, BarChart3, Bot, Brain, Check, ChevronDown, ChevronRight, CircleCheck, Circle, Clock, Command,
  Copy, Cpu, Database, DollarSign, Download, ExternalLink, FileText, Filter, FolderOpen, Gauge, Globe, House, Inbox, Keyboard,
  Layers, Lightbulb, Lock, Mail, Megaphone, Menu, MessageSquare, MessagesSquare, Moon, MoreHorizontal, Network, Paperclip,
  Pause, Phone, Pin, PinOff, Play, Plug, Plus, RefreshCw, Rss, Search, Settings, ShieldCheck, Sparkles, Sun, Target, ThumbsDown,
  Trash2, TrendingUp, Upload, User, Users, X, Zap, Box, Hash, Star, Archive, CornerDownLeft, Terminal, Eraser, Share2, GitCompare, ArrowLeftRight, PanelLeftClose, PanelLeftOpen, CornerUpLeft
} from 'lucide-vue-next'

const ICONS = {
  activity: Activity, send: ArrowUp, at: AtSign, chart: BarChart3, bot: Bot, brain: Brain, check: Check, down: ChevronDown,
  right: ChevronRight, done: CircleCheck, circle: Circle, clock: Clock, command: Command, copy: Copy, cpu: Cpu, database: Database,
  dollar: DollarSign, download: Download, external: ExternalLink, file: FileText, filter: Filter, folder: FolderOpen, gauge: Gauge,
  globe: Globe, home: House, inbox: Inbox, keyboard: Keyboard, layers: Layers, idea: Lightbulb, lock: Lock, mail: Mail,
  megaphone: Megaphone, menu: Menu, chat: MessageSquare, chats: MessagesSquare, moon: Moon, more: MoreHorizontal,
  network: Network, attach: Paperclip, pause: Pause, phone: Phone, pin: Pin, unpin: PinOff, play: Play, plug: Plug, plus: Plus,
  refresh: RefreshCw, feed: Rss, search: Search, settings: Settings, shield: ShieldCheck, sparkles: Sparkles, sun: Sun,
  target: Target, no: ThumbsDown, trash: Trash2, trend: TrendingUp, upload: Upload, user: User, users: Users, x: X, zap: Zap,
  box: Box, hash: Hash, star: Star, archive: Archive, enter: CornerDownLeft, terminal: Terminal, eraser: Eraser, share: Share2, compare: GitCompare, swap: ArrowLeftRight,
  collapse: PanelLeftClose, expand: PanelLeftOpen, reuse: CornerUpLeft
}

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 16 },
  stroke: { type: [Number, String], default: 1.8 }
})
const icon = computed(() => ICONS[props.name] || Circle)
</script>
