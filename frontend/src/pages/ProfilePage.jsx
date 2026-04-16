import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import { checkDocumentExists, getStudent, updateStudent, uploadDocument } from '@/services/api';
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

const HIDDEN_FIELDS = new Set(['id', 'created_at', 'updated_at', 'long_context_notes', 'long_context_summary']);
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

export default function StudentPage() {
  const { state, dispatch } = useApp();
  const toast = useToast();
  const [isUploading, setIsUploading] = useState(false);
  const [processingStep, setProcessingStep] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [replaceDialog, setReplaceDialog] = useState({ open: false, file: null });
  const fileInputRef = useRef(null);
  const student = state.student;

  useEffect(() => { void loadStudent(); }, [state.activeStudentId]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadStudent = async () => {
    dispatch({ type: 'SET_STUDENT_LOADING', payload: true });
    try {
      const data = await getStudent(state.activeStudentId);
      dispatch({ type: 'SET_STUDENT', payload: data });
    } catch (err) {
      console.error('Failed to load student:', err);
      dispatch({ type: 'SET_STUDENT_LOADING', payload: false });
    }
  };

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
      await loadStudent();
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
      await loadStudent();
    } catch (err) {
      toast.error(`Update failed: ${err.message}`);
    }
  };

  const isProcessing = isUploading;
  const completeness = Math.round((student?.completeness || 0) * 100);
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
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <ReplaceDialog
        open={replaceDialog.open}
        filename={replaceDialog.file?.name || ''}
        onCancel={() => {
          setReplaceDialog({ open: false, file: null });
          if (fileInputRef.current) fileInputRef.current.value = '';
        }}
        onConfirm={() => replaceDialog.file && void performUpload(replaceDialog.file, true)}
      />

      <div className="max-w-3xl mx-auto px-6 py-8 animate-fade-in">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center">
              <GraduationCap className="h-6 w-6 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight">
                {studentName || 'Student'}
              </h1>
              <div className="flex items-center gap-3 mt-1">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <div className="h-1.5 w-20 rounded-full bg-muted overflow-hidden">
                    <div className="h-full bg-primary transition-all" style={{ width: `${completeness}%` }} />
                  </div>
                  <span>{completeness}%</span>
                </div>
                <span className="text-xs text-muted-foreground">
                  {sections.length} sections · {totalEntities} entities
                </span>
              </div>
            </div>
          </div>
        </div>

        {isProcessing && processingStep && (
          <div className="mb-6 p-3.5 rounded-xl bg-yellow-50 dark:bg-yellow-950/50 border border-yellow-200 dark:border-yellow-800 flex items-center gap-3">
            <Loader2 className="h-4 w-4 animate-spin text-yellow-600 dark:text-yellow-400 flex-shrink-0" />
            <p className="text-sm text-yellow-800 dark:text-yellow-200">{processingStep}</p>
          </div>
        )}

        <div className="rounded-xl border bg-card p-4 mb-8">
          <h3 className="text-sm font-medium flex items-center gap-2 mb-3">
            <Upload className="h-4 w-4 text-primary" /> Upload Document
          </h3>
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
            className="w-full py-2 border-2 border-dashed rounded-lg text-sm hover:bg-accent hover:border-primary/20 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {isUploading ? 'Processing...' : 'Select File'}
          </button>
        </div>

        {state.studentLoading ? (
          <LoadingSkeleton />
        ) : !student ? (
          <EmptyState />
        ) : (
          <div className="space-y-4">
            {rootEntries.length > 0 && (
              <Section title="Student Details" icon={User} count={rootEntries.length} defaultOpen>
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
              className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors mx-auto"
            >
              <Settings2 className="h-3.5 w-3.5" />
              Advanced
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showAdvanced && 'rotate-180')} />
            </button>

            {showAdvanced && (
              <div className="mt-4 space-y-4 animate-fade-in">
                <AdvancedPanel
                  student={student}
                  onSaveLongContext={async (text) => {
                    try {
                      await updateStudent('long_context_summary', text, state.activeStudentId);
                      toast.success('Saved');
                      await loadStudent();
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
    <div className="group px-4 py-2.5 hover:bg-muted/30 transition-colors">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="text-sm font-medium truncate">{name}</span>
          {item.entity_type && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">
              {fmtLabel(item.entity_type)}
            </span>
          )}
          {inline.length > 0 && !expanded && (
            <span className="text-xs text-muted-foreground truncate hidden sm:inline">
              — {inline.slice(0, 2).map(([k, v]) => `${fmtLabel(k)}: ${String(v)}`).join(' · ')}
            </span>
          )}
        </div>
        {hasMore && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="opacity-0 group-hover:opacity-100 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-all"
            title={expanded ? 'Collapse' : 'Details'}
          >
            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', expanded && 'rotate-180')} />
          </button>
        )}
      </div>

      {expanded && (
        <div className="mt-2 pl-1 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs">
          {scalarProps.map(([key, value]) => (
            <div key={key} className={cn(String(value).length > 80 && 'sm:col-span-2')}>
              <span className="text-muted-foreground">{fmtLabel(key)}: </span>
              <span className="text-foreground/80">{String(value)}</span>
            </div>
          ))}
          {fieldCount > 0 && (
            <div>
              <span className="text-muted-foreground">Fields: </span>
              <span className="text-foreground/80">{fieldCount}</span>
            </div>
          )}
          {chunkCount > 0 && (
            <div>
              <span className="text-muted-foreground">Chunks: </span>
              <span className="text-foreground/80">{chunkCount}</span>
            </div>
          )}
          {documentCount > 0 && (
            <div>
              <span className="text-muted-foreground">Documents: </span>
              <span className="text-foreground/80">{documentCount}</span>
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
  const [summary, setSummary] = useState(
    student?.long_context_preview?.summary || student?.root_properties?.long_context_summary || ''
  );
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await onSaveLongContext(summary);
    setSaving(false);
  };

  return (
    <>
      <div className="rounded-xl border bg-card p-4">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Long-Context Summary</h3>
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder={'Student: none\nDetails: none\nSections: none'}
          className="w-full rounded-lg border bg-background px-3 py-2.5 text-sm resize-none h-32 focus:outline-none focus:ring-2 focus:ring-ring/50 mb-2"
        />
        <div className="flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground">One "Label: value" per line.</p>
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

      <div className="rounded-xl border bg-card p-4">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Runtime Payload Preview</h3>
        <pre className="text-[11px] text-muted-foreground whitespace-pre-wrap break-words bg-muted/30 rounded-lg p-3 max-h-64 overflow-y-auto">
          {JSON.stringify(student?.long_context_preview || {}, null, 2)}
        </pre>
      </div>
    </>
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
      <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mx-auto mb-3">
        <User className="h-6 w-6 text-muted-foreground" />
      </div>
      <p className="text-muted-foreground text-sm">No student data yet.</p>
      <p className="text-muted-foreground text-xs mt-1">Upload a document to start building the student graph.</p>
    </div>
  );
}

function ReplaceDialog({ open, filename, onCancel, onConfirm }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative bg-card border rounded-2xl shadow-xl p-6 max-w-sm w-full mx-4 animate-fade-in-up">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
            <FileText className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h3 className="text-sm font-semibold">Replace document?</h3>
            <p className="text-sm text-muted-foreground mt-1">
              "{filename}" already exists for this student. Replace it with the new version?
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="px-4 py-2 text-sm font-medium rounded-lg border hover:bg-muted transition-colors">Cancel</button>
          <button onClick={onConfirm} className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90">Replace</button>
        </div>
      </div>
    </div>
  );
}
