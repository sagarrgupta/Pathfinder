import React, { useState, useEffect, useRef } from 'react';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import {
  addProfileText,
  checkDocumentExists,
  deleteProfileEntity,
  getProfile,
  updateProfile,
  updateProfileEntity,
  uploadDocument,
} from '@/services/api';
import {
  User, Upload, FileText, Trash2, Plus, BookOpen,
  Briefcase, Target, Star, GraduationCap, Loader2,
  Pencil, Check, X, AlertTriangle, Heart, Folder,
  Building2, Circle, Sparkles, ChevronDown, Settings2,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const ENTITY_CONFIG = {
  Course:     { label: 'Courses',      icon: BookOpen },
  Skill:      { label: 'Skills',       icon: Star },
  Company:    { label: 'Experience',   icon: Briefcase },
  Goal:       { label: 'Goals',        icon: Target },
  Interest:   { label: 'Interests',    icon: Heart },
  Project:    { label: 'Projects',     icon: Folder },
  Department: { label: 'Departments',  icon: Building2 },
  Document:   { label: 'Documents',    icon: FileText },
};

const HIDDEN_FIELDS = new Set(['id', 'created_at', 'updated_at', '_relationship', 'long_context_notes', 'long_context_summary']);
const HIDDEN_ENTITY_FIELDS = new Set(['id', 'student_id', 'created_at', 'updated_at', '_relationship', '_schema_section']);
const LABEL_MAP = { gpa: 'GPA', id: 'ID', url: 'URL' };

function fmtLabel(key) {
  return LABEL_MAP[key.toLowerCase()] || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function cfgFor(label) {
  return ENTITY_CONFIG[label] || { label: label + 's', icon: Circle };
}

export default function ProfilePage() {
  const { state, dispatch } = useApp();
  const toast = useToast();
  const [freeText, setFreeText] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isProcessingText, setIsProcessingText] = useState(false);
  const [processingStep, setProcessingStep] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const fileInputRef = useRef(null);
  const profile = state.profile;

  const [confirmDialog, setConfirmDialog] = useState({
    open: false, title: '', message: '', onConfirm: null,
    confirmLabel: 'Delete', variant: 'destructive',
  });

  useEffect(() => { loadProfile(); }, [state.activeStudentId]);

  const loadProfile = async () => {
    dispatch({ type: 'SET_PROFILE_LOADING', payload: true });
    try {
      const data = await getProfile(state.activeStudentId);
      dispatch({ type: 'SET_PROFILE', payload: data });
    } catch (err) {
      console.error('Failed to load profile:', err);
      dispatch({ type: 'SET_PROFILE_LOADING', payload: false });
    }
  };

  const performUpload = async (file, replace = false) => {
    setIsUploading(true);
    setProcessingStep('Processing and extracting entities...');
    try {
      const result = await uploadDocument(file, 'global', null, replace, state.activeStudentId);
      toast.success(
        replace
          ? `Replaced ${file.name}: ${result.entities_extracted} entities extracted`
          : `Uploaded ${file.name}: ${result.entities_extracted} entities extracted`
      );
      setProcessingStep('');
      await loadProfile();
    } catch (err) {
      toast.error(`Upload failed: ${err.message}`);
      setProcessingStep('');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const { exists } = await checkDocumentExists(file.name, state.activeStudentId);
      if (exists) {
        setConfirmDialog({
          open: true, title: 'Duplicate Document',
          message: `"${file.name}" already exists. Replace it with the new version?`,
          confirmLabel: 'Replace', variant: 'primary',
          onConfirm: () => { setConfirmDialog((p) => ({ ...p, open: false })); performUpload(file, true); },
        });
        return;
      }
    } catch { /* proceed */ }
    performUpload(file);
  };

  const handleAddText = async () => {
    if (!freeText.trim()) return;
    setIsProcessingText(true);
    setProcessingStep('Extracting entities...');
    try {
      const result = await addProfileText(freeText, state.activeStudentId);
      toast.success(`Extracted ${result.entities_extracted} entities`);
      setFreeText('');
      await loadProfile();
      setProcessingStep('');
    } catch (err) {
      toast.error(`Failed: ${err.message}`);
      setProcessingStep('');
    } finally {
      setIsProcessingText(false);
    }
  };

  const handleDelete = (label, name) => {
    setConfirmDialog({
      open: true, title: 'Confirm Deletion',
      message: `Delete "${name}" from your profile? This cannot be undone.`,
      onConfirm: async () => {
        setConfirmDialog((p) => ({ ...p, open: false }));
        try {
          await deleteProfileEntity(label, name, state.activeStudentId);
          toast.success(`Deleted ${name}`);
          await loadProfile();
        } catch (err) { toast.error(`Delete failed: ${err.message}`); }
      },
    });
  };

  const handleEditField = async (field, value) => {
    try {
      await updateProfile(field, value, state.activeStudentId);
      toast.success(`Updated ${fmtLabel(field)}`);
      await loadProfile();
    } catch (err) { toast.error(`Update failed: ${err.message}`); }
  };

  const handleEditEntity = async (label, name, properties) => {
    try {
      await updateProfileEntity(label, name, properties, state.activeStudentId);
      toast.success(`Updated ${name}`);
      await loadProfile();
    } catch (err) { toast.error(`Update failed: ${err.message}`); }
  };

  const isProcessing = isUploading || isProcessingText;
  const completeness = Math.round((profile?.completeness || 0) * 100);
  const sectionItems = profile?.section_items || {};
  const totalEntities = Object.values(sectionItems).reduce((s, arr) => s + (arr?.length || 0), 0)
    + (profile?.unsectioned_items?.length || 0);
  const rootEntries = Object.entries(profile?.root_properties || {}).filter(
    ([key, value]) => !HIDDEN_FIELDS.has(key) && value !== null && value !== '',
  );
  const profileName = profile?.root_properties?.name || '';

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <ConfirmDialog {...confirmDialog} onCancel={() => setConfirmDialog((p) => ({ ...p, open: false }))} />

      <div className="max-w-3xl mx-auto px-6 py-8 animate-fade-in">

        {/* ── Header ─────────────────────────────────────── */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center">
              <GraduationCap className="h-6 w-6 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight">
                {profileName || 'My Profile'}
              </h1>
              <div className="flex items-center gap-3 mt-1">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <div className="h-1.5 w-20 rounded-full bg-muted overflow-hidden">
                    <div className="h-full bg-primary transition-all" style={{ width: `${completeness}%` }} />
                  </div>
                  <span>{completeness}%</span>
                </div>
                <span className="text-xs text-muted-foreground">
                  {(profile?.sections?.length || 0)} sections · {totalEntities} entities
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* ── Processing Banner ───────────────────────────── */}
        {isProcessing && processingStep && (
          <div className="mb-6 p-3.5 rounded-xl bg-yellow-50 dark:bg-yellow-950/50 border border-yellow-200 dark:border-yellow-800 flex items-center gap-3">
            <Loader2 className="h-4 w-4 animate-spin text-yellow-600 dark:text-yellow-400 flex-shrink-0" />
            <p className="text-sm text-yellow-800 dark:text-yellow-200">{processingStep}</p>
          </div>
        )}

        {/* ── Add Data ────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-8">
          <div className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-medium flex items-center gap-2 mb-3">
              <Upload className="h-4 w-4 text-primary" /> Upload Document
            </h3>
            <input ref={fileInputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.heif,.heic,.docx" onChange={handleUpload} className="hidden" />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isProcessing}
              className="w-full py-2 border-2 border-dashed rounded-lg text-sm hover:bg-accent hover:border-primary/20 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {isUploading ? 'Processing...' : 'Select File'}
            </button>
          </div>
          <div className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-medium flex items-center gap-2 mb-3">
              <Sparkles className="h-4 w-4 text-primary" /> Add Information
            </h3>
            <textarea
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              placeholder="Type anything about yourself — we'll extract and store it."
              className="w-full rounded-lg border bg-background px-3 py-2 text-sm resize-none h-[68px] focus:outline-none focus:ring-2 focus:ring-ring/50"
              disabled={isProcessing}
            />
            <button
              onClick={handleAddText}
              disabled={!freeText.trim() || isProcessing}
              className="mt-2 w-full py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-1.5"
            >
              {isProcessingText ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {isProcessingText ? 'Processing...' : 'Add to Profile'}
            </button>
          </div>
        </div>

        {/* ── Profile Data ────────────────────────────────── */}
        {state.profileLoading ? (
          <LoadingSkeleton />
        ) : !profile ? (
          <EmptyState />
        ) : (
          <div className="space-y-4">
            {rootEntries.length > 0 && (
              <Section title="Profile Details" icon={User} count={rootEntries.length} defaultOpen>
                <div className="divide-y">
                  {rootEntries
                    .sort(([a], [b]) => (a === 'name' ? -1 : b === 'name' ? 1 : a.localeCompare(b)))
                    .map(([key, value]) => (
                      <EditableField key={key} label={fmtLabel(key)} value={String(value)} fieldKey={key} onSave={handleEditField} />
                    ))}
                </div>
              </Section>
            )}

            {(profile.sections || []).map((section) => {
              const items = sectionItems[section.key] || [];
              return (
                <Section
                  key={section.key}
                  title={section.label || section.key}
                  description={section.description || section.purpose}
                  icon={Folder}
                  count={items.length}
                  defaultOpen={items.length > 0 && items.length <= 15}
                >
                  {items.length > 0 ? (
                    <EntityGroup items={items} onDelete={handleDelete} />
                  ) : (
                    <p className="text-sm text-muted-foreground py-4 text-center">No items yet.</p>
                  )}
                </Section>
              );
            })}

            {(profile.unsectioned_items?.length || 0) > 0 && (
              <Section title="Other" icon={Circle} count={profile.unsectioned_items.length} defaultOpen>
                <EntityGroup items={profile.unsectioned_items} onDelete={handleDelete} />
              </Section>
            )}
          </div>
        )}

        {/* ── Advanced / Debug ────────────────────────────── */}
        {profile && (
          <div className="mt-10">
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors mx-auto"
            >
              <Settings2 className="h-3.5 w-3.5" />
              Advanced
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showAdvanced && 'rotate-180')} />
            </button>

            {showAdvanced && (
              <div className="mt-4 space-y-4 animate-fade-in">
                <AdvancedPanel profile={profile} onSaveLongContext={async (text) => {
                  try {
                    await updateProfile('long_context_summary', text, state.activeStudentId);
                    toast.success('Saved');
                    await loadProfile();
                  } catch (err) { toast.error(`Failed: ${err.message}`); }
                }} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Section (collapsible) ───────────────────────────────────────

function Section({ title, description, icon: Icon, count = 0, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 px-4 py-3.5 text-left hover:bg-muted/30 transition-colors">
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
          <Icon className="h-4 w-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold truncate">{title}</span>
            {count > 0 && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">{count}</span>
            )}
          </div>
          {description && <p className="text-xs text-muted-foreground truncate mt-0.5">{description}</p>}
        </div>
        <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform flex-shrink-0', open && 'rotate-180')} />
      </button>
      {open && <div className="border-t">{children}</div>}
    </div>
  );
}

// ── Entity Group ────────────────────────────────────────────────

function EntityGroup({ items, onDelete }) {
  const grouped = {};
  for (const entry of items) {
    const label = entry?.label || 'Item';
    (grouped[label] ||= []).push(entry?.item || {});
  }

  return (
    <div className="divide-y">
      {Object.entries(grouped).map(([label, entities]) => {
        const { label: groupLabel, icon: Icon } = cfgFor(label);
        return (
          <div key={label}>
            <div className="flex items-center gap-2 px-4 pt-3 pb-1.5">
              <Icon className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{groupLabel}</span>
              <span className="text-[10px] text-muted-foreground/60">{entities.length}</span>
            </div>
            {entities.map((item, i) => (
              <EntityRow key={i} label={label} item={item} onDelete={onDelete} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ── Entity Row ──────────────────────────────────────────────────

function EntityRow({ label, item, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const name = item.name || item.title || item.code || item.key || item.filename || label;
  const badge = (item.role || item.type || item.category || '');

  const props = Object.entries(item).filter(
    ([k, v]) => !HIDDEN_ENTITY_FIELDS.has(k) && k !== 'name' && k !== 'title' && v != null && String(v).trim() !== '',
  );
  const inline = props.filter(([, v]) => String(v).length <= 80);
  const detail = props.filter(([, v]) => String(v).length > 80);
  const hasMore = inline.length > 3 || detail.length > 0;

  return (
    <div className="group px-4 py-2.5 hover:bg-muted/30 transition-colors">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="text-sm font-medium truncate">{name}</span>
          {badge && badge !== name && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">{badge}</span>
          )}
          {inline.length > 0 && !expanded && (
            <span className="text-xs text-muted-foreground truncate hidden sm:inline">
              — {inline.slice(0, 2).map(([k, v]) => `${fmtLabel(k)}: ${String(v)}`).join(' · ')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0">
          {hasMore && (
            <button onClick={() => setExpanded(!expanded)} className="opacity-0 group-hover:opacity-100 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-all" title={expanded ? 'Collapse' : 'Details'}>
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', expanded && 'rotate-180')} />
            </button>
          )}
          <button
            onClick={() => onDelete(label, item.name || item.title || item.filename || name)}
            className="opacity-0 group-hover:opacity-100 p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-all"
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {expanded && props.length > 0 && (
        <div className="mt-2 pl-1 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs">
          {props.map(([k, v]) => (
            <div key={k} className={cn(String(v).length > 80 && 'sm:col-span-2')}>
              <span className="text-muted-foreground">{fmtLabel(k)}: </span>
              <span className="text-foreground/80">{String(v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Editable Field ──────────────────────────────────────────────

function EditableField({ label, value, fieldKey, onSave }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  const save = () => { if (draft !== value) onSave(fieldKey, draft); setEditing(false); };
  const cancel = () => { setDraft(value); setEditing(false); };

  return (
    <div className="flex items-center justify-between py-2.5 px-4 hover:bg-muted/30 group transition-colors">
      <span className="text-muted-foreground text-sm w-32 flex-shrink-0">{label}</span>
      {editing ? (
        <div className="flex items-center gap-2 flex-1 ml-3">
          <input
            type="text" value={draft} onChange={(e) => setDraft(e.target.value)}
            className="flex-1 rounded-lg border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
            autoFocus
            onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel(); }}
          />
          <button onClick={save} className="p-1 rounded-md text-green-600 hover:bg-green-100 dark:hover:bg-green-900/30" title="Save"><Check className="h-4 w-4" /></button>
          <button onClick={cancel} className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10" title="Cancel"><X className="h-4 w-4" /></button>
        </div>
      ) : (
        <div className="flex items-center gap-2 flex-1 ml-3 justify-end">
          <span className="text-sm">{value || '—'}</span>
          <button onClick={() => { setDraft(value || ''); setEditing(true); }} className="opacity-0 group-hover:opacity-100 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-all" title="Edit">
            <Pencil className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

// ── Advanced Panel ──────────────────────────────────────────────

function AdvancedPanel({ profile, onSaveLongContext }) {
  const [summary, setSummary] = useState(
    profile?.long_context_preview?.summary || profile?.root_properties?.long_context_summary || ''
  );
  const [saving, setSaving] = useState(false);
  const temporal = profile?.temporal_profile?.summary || {};
  const facts = profile?.fact_summary || {};
  const memory = profile?.memory_overview || {};

  const handleSave = async () => {
    setSaving(true);
    await onSaveLongContext(summary);
    setSaving(false);
  };

  return (
    <>
      {/* Stats */}
      <div className="rounded-xl border bg-card p-4">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Memory & Evidence</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Stable facts', value: temporal.stable_count || 0 },
            { label: 'Evolving', value: temporal.evolving_count || 0 },
            { label: 'Candidates', value: temporal.active_candidate_count || 0 },
            { label: 'Support records', value: memory.support_records || 0 },
            { label: 'Confirmed', value: facts.confirmed_candidate_facts || 0 },
            { label: 'Reinforced', value: facts.reinforced_candidate_facts || 0 },
            { label: 'Inferred', value: facts.inferred_candidate_facts || 0 },
            { label: 'Doc-backed', value: facts.document_backed || 0 },
          ].map((s) => (
            <div key={s.label} className="text-center">
              <p className="text-lg font-semibold">{s.value}</p>
              <p className="text-[10px] text-muted-foreground">{s.label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Long Context Editor */}
      <div className="rounded-xl border bg-card p-4">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Long-Context Summary</h3>
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder={'Profile: none\nDetails: none\nSections: none'}
          className="w-full rounded-lg border bg-background px-3 py-2.5 text-sm resize-none h-32 focus:outline-none focus:ring-2 focus:ring-ring/50 mb-2"
        />
        <div className="flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground">One &quot;Label: value&quot; per line.</p>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {/* Runtime Payload */}
      <div className="rounded-xl border bg-card p-4">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Runtime Payload Preview</h3>
        <pre className="text-[11px] text-muted-foreground whitespace-pre-wrap break-words bg-muted/30 rounded-lg p-3 max-h-64 overflow-y-auto">
          {JSON.stringify(profile?.long_context_preview || {}, null, 2)}
        </pre>
      </div>
    </>
  );
}

// ── Shared small components ─────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-muted animate-pulse" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-32 bg-muted rounded animate-pulse" />
              <div className="h-3 w-48 bg-muted rounded animate-pulse" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-16">
      <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mx-auto mb-3">
        <User className="h-6 w-6 text-muted-foreground" />
      </div>
      <p className="text-muted-foreground text-sm">No profile data yet.</p>
      <p className="text-muted-foreground text-xs mt-1">Upload a document or add information above to get started.</p>
    </div>
  );
}

function ConfirmDialog({ open, title, message, onConfirm, onCancel, confirmLabel = 'Delete', variant = 'destructive' }) {
  if (!open) return null;
  const isDanger = variant === 'destructive';
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative bg-card border rounded-2xl shadow-xl p-6 max-w-sm w-full mx-4 animate-fade-in-up">
        <div className="flex items-start gap-3 mb-4">
          <div className={cn('w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0', isDanger ? 'bg-destructive/10' : 'bg-primary/10')}>
            <AlertTriangle className={cn('h-5 w-5', isDanger ? 'text-destructive' : 'text-primary')} />
          </div>
          <div>
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground mt-1">{message}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="px-4 py-2 text-sm font-medium rounded-lg border hover:bg-muted transition-colors">Cancel</button>
          <button onClick={onConfirm} className={cn('px-4 py-2 text-sm font-medium rounded-lg hover:opacity-90', isDanger ? 'bg-destructive text-destructive-foreground' : 'bg-primary text-primary-foreground')}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
