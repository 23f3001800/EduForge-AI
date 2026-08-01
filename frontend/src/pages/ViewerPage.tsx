import { useEffect, useMemo, useState } from "react";
import { getPackage } from "../api";
import { ApiError, type TeacherKnowledgePackage } from "../api/types";
import { EmptyState } from "../components/ui/EmptyState";
import { Spinner } from "../components/ui/Spinner";
import { Tabs, type TabDef } from "../components/ui/Tabs";
import { Link, useRouteParams } from "../router/router";
import { buildLookups } from "../utils/lookups";
import { AssessmentsTab } from "../viewer/AssessmentsTab";
import { ClassroomContentTab } from "../viewer/ClassroomContentTab";
import { KnowledgeTab } from "../viewer/KnowledgeTab";
import { LearningGapsTab } from "../viewer/LearningGapsTab";
import { OverviewTab } from "../viewer/OverviewTab";
import { PackageHeader } from "../viewer/PackageHeader";
import { TeachingPlanTab } from "../viewer/TeachingPlanTab";
import { ValidationTab } from "../viewer/ValidationTab";

export function ViewerPage() {
  const { packageId } = useRouteParams();
  const [tkp, setTkp] = useState<TeacherKnowledgePackage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

  useEffect(() => {
    if (!packageId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPackage(packageId)
      .then((pkg) => {
        if (!cancelled) setTkp(pkg);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err
              : new ApiError(0, { error: { code: "network_error", message: "Could not reach the server." } }),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [packageId]);

  const lookups = useMemo(() => (tkp ? buildLookups(tkp.knowledge, tkp.activities) : null), [tkp]);

  if (!packageId) return null;

  if (loading) {
    return (
      <div className="ef-stack">
        <Spinner label="Loading package" />
      </div>
    );
  }

  if (error || !tkp || !lookups) {
    if (error?.status === 404) {
      return (
        <EmptyState title="Package not found" tone="error">
          This package does not exist, or has not finished generating yet. <Link to="/">Start a new one</Link>.
        </EmptyState>
      );
    }
    return (
      <EmptyState title="Could not load this package" tone="error">
        {error?.message ?? "Something went wrong."} <Link to="/">Start a new one</Link>.
      </EmptyState>
    );
  }

  const tabs: TabDef[] = [
    { id: "overview", label: "Overview", panel: <OverviewTab tkp={tkp} /> },
    { id: "plan", label: "Teaching Plan", panel: <TeachingPlanTab plan={tkp.teaching_plan} lookups={lookups} /> },
    {
      id: "content",
      label: "Classroom Content",
      panel: <ClassroomContentTab content={tkp.classroom_content} lookups={lookups} />,
    },
    { id: "knowledge", label: "Knowledge Base", panel: <KnowledgeTab knowledge={tkp.knowledge} lookups={lookups} /> },
  ];

  if (tkp.assessments.items.length > 0) {
    tabs.push({
      id: "assessments",
      label: "Assessments",
      panel: <AssessmentsTab bank={tkp.assessments} lookups={lookups} />,
    });
  }

  if (tkp.learning_gaps.length > 0) {
    tabs.push({
      id: "gaps",
      label: "Learning Gaps",
      panel: <LearningGapsTab gaps={tkp.learning_gaps} lookups={lookups} />,
    });
  }

  tabs.push({ id: "validation", label: "Validation", panel: <ValidationTab validation={tkp.validation} /> });

  const activeExists = tabs.some((t) => t.id === activeTab);

  return (
    <div className="ef-stack">
      <PackageHeader tkp={tkp} />
      <Tabs tabs={tabs} active={activeExists ? activeTab : "overview"} onChange={setActiveTab} />
    </div>
  );
}
