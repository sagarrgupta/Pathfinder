import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import { checkDocumentExists, updateStudent, uploadDocument } from '@/services/api';
import {
  ChevronDown,
  Circle,
  FileText,
  Folder,
  GraduationCap,
  Loader2,
  Pencil,
  Plus,
  Settings2,
  Upload,
  User,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const HIDDEN_FIELDS = new Set(['id', 'created_at', 'updated_at', 'long_context']);
const HIDDEN_ENTITY_FIELDS = new Set([
  'id',
  'student_id',
  'created_at',
  'updated_at',
  'entity_type',
  'section_key',
  'documents',
  'chunks',
  'fields',
]);
const LABEL_MAP = { gpa: 'GPA', id: 'ID', url: 'URL' };

function fmtLabel(key) {
  return LABEL_MAP[key.toLowerCase()] || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function entityName(item) {
  return (
    item.name ||
    item.title ||
    item.course_code ||
    item.code ||
    item.key ||
    item.filename ||
    item.label ||
    item.id ||
    'Untitled'
  );
}

export default function ProfilePage() {
  const { state, refreshStudent } = useApp();
  const toast = useToast();
  const [isUploading, setIsUploading] = useState(false);
  const [processingStep, setProcessingStep] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [replaceDialog, setReplaceDialog] = useState({ open: false, file: null });
  const fileInputRef = useRef(null);
  const student = state.student;

  // Refresh the student snapshot whenever the page mounts so that nodes added
  // via chat (document ingestion, context persister, etc.) are reflected
  // immediately when the user navigates here from another page.
  useEffect(() => {
    if (!state.activeStudentId) return;
    refreshStudent(state.activeStudentId).catch(() => {
      // Silent failure — stale data still renders.
    });
  }, [state.activeStudentId, refreshStudent]);

  const performUpload = async (file, replace = false) => {
    setIsUploading(true);
    setProcessingStep('Processing and ingesting document...');
    try {
      const result = await uploadDocument(file, replace, state.activeStudentId);
      toast.success(
        replace
          ? `Replaced ${file.name}: ${result.entities_extracted} entities extracted`
          : `Uploaded ${file.name}: ${result.entities_extracted} entities extracted`
      );
      await refreshStudent(state.activeStudentId);
    } catch (err) {
      toast.error(`Upload failed: ${err.message}`);
    } finally {
      setProcessingStep('');
      setIsUploading(false);
      setReplaceDialog({ open: false, file: null });
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!state.activeStudentId) {
      toast.error('Create or select a student profile first.');
      event.target.value = '';
      return;
    }
    try {
      const { exists } = await checkDocumentExists(file.name, state.activeStudentId);
      if (exists) {
        setReplaceDialog({ open: true, file });
        return;
      }
    } catch {
      // continue with upload if duplicate check fails
    }
    await performUpload(file, false);
  };

  const handleEditField = async (field, value) => {
    try {
      await updateStudent(field, value, state.activeStudentId);
      toast.success(`Updated ${fmtLabel(field)}`);
      await refreshStudent(state.activeStudentId);
    } catch (err) {
      toast.error(`Update failed: ${err.message}`);
    }
  };

  const isProcessing = isUploading;
  const sectionItems = student?.section_items || {};
  const sections = Array.isArray(student?.sections) ? student.sections : [];
  const totalEntities = Object.values(sectionItems).reduce(
    (sum, items) => sum + (Array.isArray(items) ? items.length : 0),
    0,
  );
  const rootEntries = Object.entries(student?.root_properties || {}).filter(
    ([key, value]) => !HIDDEN_FIELDS.has(key) && value !== null && value !== '',
  );
  const studentName = student?.root_properties?.name || '';

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto scrollbar-fade">
      <ReplaceDialog
        open={replaceDialog.open}
        filename={replaceDialog.file?.name || ''}
        onCancel={() => {
          setReplaceDialog({ open: false, file: null });
          if (fileInputRef.current) fileInputRef.current.value = '';
        }}
        onConfirm={() => replaceDialog.file && void performUpload(replaceDialog.file, true)}
      />

      <div className="mx-auto max-w-5xl px-6 py-8 animate-fade-in">
        <div className="hero-panel mb-8 overflow-hidden px-6 py-7 sm:px-8">
          <div className="mb-3 eyebrow">Student profile</div>
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-[22px] bg-gradient-to-br from-primary/20 via-primary/10 to-warning/15 ring-1 ring-primary/15">
                <GraduationCap className="h-6 w-6 text-primary" />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
                  {studentName || 'Student'}
                </h1>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                  Review what Pathfinder knows about this student, upload new source documents, and edit the longer profile memory used across future conversations.
                </p>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="metric-tile min-w-[120px]">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Profile Sections</p>
                <p className="mt-3 text-2xl font-semibold">{sections.length}</p>
              </div>
              <div className="metric-tile min-w-[120px]">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Saved Items</p>
                <p className="mt-3 text-2xl font-semibold">{totalEntities}</p>
              </div>
            </div>
          </div>
        </div>

        {isProcessing && processingStep && (
          <div className="mb-6 flex items-center gap-3 rounded-2xl border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-800 dark:bg-yellow-950/50">
            <Loader2 className="h-4 w-4 animate-spin text-yellow-600 dark:text-yellow-400 flex-shrink-0" />
            <p className="text-sm text-yellow-800 dark:text-yellow-200">{processingStep}</p>
          </div>
        )}

        <div className="section-card mb-8">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="section-kicker">Add source material</p>
              <h3 className="mt-1 text-base font-semibold">Upload a transcript, resume, or supporting file</h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Files uploaded here go through the same extraction and graph-ingestion pipeline as chat uploads. They become available to future answers after processing.
              </p>
            </div>
            <div className="info-strip max-w-sm">
              <Upload className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
              <p className="text-xs leading-5 text-muted-foreground">
                Best for durable profile data you want Pathfinder to remember and reuse later.
              </p>
            </div>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.heif,.heic,.docx"
            onChange={handleUpload}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isProcessing}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-border/80 py-4 text-sm font-medium transition-all hover:border-primary/20 hover:bg-accent disabled:opacity-50"
          >
            {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {isUploading ? 'Processing...' : 'Choose File'}
          </button>
        </div>

        {state.studentLoading ? (
          <LoadingSkeleton />
        ) : !student ? (
          <EmptyState />
        ) : (
          <div className="space-y-4">
            {rootEntries.length > 0 && (
              <Section title="Basic Information" icon={User} count={rootEntries.length} defaultOpen>
                <div className="divide-y">
                  {rootEntries
                    .sort(([a], [b]) => (a === 'name' ? -1 : b === 'name' ? 1 : a.localeCompare(b)))
                    .map(([key, value]) => (
                      <EditableField key={key} label={fmtLabel(key)} value={String(value)} fieldKey={key} onSave={handleEditField} />
                    ))}
                </div>
              </Section>
            )}

            {sections.map((section) => {
              const items = sectionItems[section.key] || [];
              return (
                <Section
                  key={section.key}
                  title={section.label || fmtLabel(section.key || 'section')}
                  description={section.description || ''}
                  icon={Folder}
                  count={items.length}
                  defaultOpen={items.length > 0 && items.length <= 15}
                >
                  {items.length > 0 ? (
                    <EntityGroup items={items} />
                  ) : (
                    <p className="text-sm text-muted-foreground py-4 text-center">No items yet.</p>
                  )}
                </Section>
              );
            })}
          </div>
        )}

        {student && (
          <div className="mt-10">
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="mx-auto flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-4 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <Settings2 className="h-3.5 w-3.5" />
              Longer Profile Memory
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showAdvanced && 'rotate-180')} />
            </button>

            {showAdvanced && (
              <div className="mt-4 space-y-4 animate-fade-in">
                <AdvancedPanel
                  student={student}
                  onSaveLongContext={async (text) => {
                    try {
                      await updateStudent('long_context', text, state.activeStudentId);
                      toast.success('Saved');
                      await refreshStudent(state.activeStudentId);
                    } catch (err) {
                      toast.error(`Failed: ${err.message}`);
                    }
                  }}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, description, icon: Icon, count = 0, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="overflow-hidden rounded-[24px] border border-border/70 bg-card/80 shadow-sm">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-4 text-left transition-colors hover:bg-muted/25">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-primary/10">
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

function EntityGroup({ items }) {
  const grouped = {};
  for (const item of items) {
    const label = item?.entity_type || 'Entity';
    (grouped[label] ||= []).push(item || {});
  }

  return (
    <div className="divide-y">
      {Object.entries(grouped).map(([label, entities]) => (
        <div key={label}>
          <div className="flex items-center gap-2 px-4 pt-3 pb-1.5">
            <Circle className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{fmtLabel(label)}</span>
            <span className="text-[10px] text-muted-foreground/60">{entities.length}</span>
          </div>
          {entities.map((item, index) => (
            <EntityRow key={`${label}-${index}-${item.id || entityName(item)}`} item={item} />
          ))}
        </div>
      ))}
    </div>
  );
}

function EntityRow({ item }) {
  const [expanded, setExpanded] = useState(false);
  const name = entityName(item);
  const scalarProps = Object.entries(item).filter(([key, value]) => {
    if (HIDDEN_ENTITY_FIELDS.has(key) || key === 'name' || key === 'title') return false;
    if (value == null || String(value).trim() === '') return false;
    return typeof value !== 'object';
  });
  const inline = scalarProps.filter(([, value]) => String(value).length <= 80);
  const detail = scalarProps.filter(([, value]) => String(value).length > 80);
  const fieldCount = Array.isArray(item.fields) ? item.fields.length : 0;
  const chunkCount = Array.isArray(item.chunks) ? item.chunks.length : 0;
  const documentCount = Array.isArray(item.documents) ? item.documents.length : 0;
  const hasMore = inline.length > 3 || detail.length > 0 || fieldCount > 0 || chunkCount > 0 || documentCount > 0;

  return (
    <div className="group border-t border-border/40 px-4 py-3 transition-colors first:border-t-0 hover:bg-muted/30">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="truncate text-sm font-semibold">{name}</span>
          {item.entity_type && (
            <span className="flex-shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
              {fmtLabel(item.entity_type)}
            </span>
          )}
          {inline.length > 0 && !expanded && (
            <div className="hidden min-w-0 flex-wrap gap-1.5 sm:flex">
              {inline.slice(0, 2).map(([k, v]) => (
                <span key={k} className="truncate rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                  {fmtLabel(k)}: {String(v)}
                </span>
              ))}
            </div>
          )}
        </div>
        {hasMore && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="rounded-full border border-border/60 p-1.5 text-muted-foreground opacity-0 transition-all hover:bg-accent hover:text-foreground group-hover:opacity-100"
            title={expanded ? 'Collapse' : 'Details'}
          >
            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', expanded && 'rotate-180')} />
          </button>
        )}
      </div>

      {expanded && (
        <div className="mt-3 grid grid-cols-1 gap-2 rounded-2xl border border-border/60 bg-background/70 p-3 text-xs shadow-sm sm:grid-cols-2 sm:gap-x-6">
          {scalarProps.map(([key, value]) => (
            <div key={key} className={cn('space-y-0.5', String(value).length > 80 && 'sm:col-span-2')}>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{fmtLabel(key)}</p>
              <p className="leading-5 text-foreground/85">{String(value)}</p>
            </div>
          ))}
          {fieldCount > 0 && (
            <div className="space-y-0.5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Fields</p>
              <p className="text-foreground/85">{fieldCount}</p>
            </div>
          )}
          {chunkCount > 0 && (
            <div className="space-y-0.5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Chunks</p>
              <p className="text-foreground/85">{chunkCount}</p>
            </div>
          )}
          {documentCount > 0 && (
            <div className="space-y-0.5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Documents</p>
              <p className="text-foreground/85">{documentCount}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EditableField({ label, value, fieldKey, onSave }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  const save = () => {
    if (draft !== value) onSave(fieldKey, draft);
    setEditing(false);
  };
  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  return (
    <div className="flex items-center justify-between py-2.5 px-4 hover:bg-muted/30 group transition-colors">
      <span className="text-muted-foreground text-sm w-32 flex-shrink-0">{label}</span>
      {editing ? (
        <div className="flex items-center gap-2 flex-1 ml-3">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="flex-1 rounded-lg border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter') save();
              if (e.key === 'Escape') cancel();
            }}
          />
          <button onClick={save} className="p-1 rounded-md text-primary hover:bg-primary/10" title="Save">
            <Plus className="h-4 w-4 rotate-45" />
          </button>
          <button onClick={cancel} className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10" title="Cancel">
            <X className="h-4 w-4" />
          </button>
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

function AdvancedPanel({ student, onSaveLongContext }) {
  const longContext = student?.long_context || student?.root_properties?.long_context || '';
  const [summary, setSummary] = useState(longContext);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    setSummary(longContext);
    setEditing(false);
  }, [longContext]);

  const handleSave = async () => {
    setSaving(true);
    await onSaveLongContext(summary);
    setSaving(false);
    setEditing(false);
  };

  const handleCancel = () => {
    setSummary(longContext);
    setEditing(false);
  };

  return (
    <div className="section-card bg-card/85">
      <div className="mb-3">
        <p className="eyebrow mb-2">Information pathfinder has about you</p>
        <h3 className="text-sm font-semibold">Profile summary</h3>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Pathfinder uses this to remember important details about you, like your goals, preferences, background, and constraints, so future responses can feel more relevant without you having to repeat yourself each time.
        </p>
      </div>

      {editing ? (
        <>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="Describe yourself."
            className="mb-3 h-48 w-full resize-none rounded-2xl border border-border/70 bg-background/85 px-4 py-3 text-sm leading-6 shadow-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
          />
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] text-muted-foreground">
              Write anything Pathfinder should remember about you for future conversations.
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={handleCancel}
                disabled={saving}
                className="soft-button px-4 py-2 text-xs font-semibold text-muted-foreground disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="primary-button px-4 py-2 text-xs disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="space-y-3">
          <div className="min-h-[12rem] whitespace-pre-wrap rounded-2xl border border-border/70 bg-background/80 px-4 py-3 text-sm leading-6 text-foreground/85 shadow-sm">
            {longContext || <span className="text-muted-foreground">Describe yourself.</span>}
          </div>
          <div className="flex justify-end">
            <button
              onClick={() => setEditing(true)}
              className="soft-button text-xs"
            >
              <Pencil className="h-3.5 w-3.5" />
              Edit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

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
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/15 to-warning/10 ring-1 ring-primary/10">
        <User className="h-6 w-6 text-muted-foreground" />
      </div>
      <p className="text-muted-foreground text-sm">No profile information yet.</p>
      <p className="text-muted-foreground text-xs mt-1">Upload a document or start chatting to help Pathfinder build this profile.</p>
    </div>
  );
}

function ReplaceDialog({ open, filename, onCancel, onConfirm }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
      <div className="hero-panel relative mx-4 w-full max-w-sm animate-fade-in-up border-border/70 p-6">
        <div className="flex items-start gap-3 mb-4">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/15 to-warning/10 ring-1 ring-primary/10">
            <FileText className="h-5 w-5 text-primary" />
          </div>
          <div>
            <p className="eyebrow mb-2">Upload conflict</p>
            <h3 className="text-sm font-semibold">Replace document?</h3>
            <p className="text-sm text-muted-foreground mt-1">
              "{filename}" already exists for this student. Replace it with the new version?
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-xl border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted">Cancel</button>
          <button onClick={onConfirm} className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-opacity hover:opacity-90">Replace</button>
        </div>
      </div>
    </div>
  );
}
