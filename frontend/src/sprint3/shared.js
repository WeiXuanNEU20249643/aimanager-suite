import {useCallback, useEffect, useRef, useState} from 'react';
import {projectApi} from '../api';

export function usePlanningData(projectId, pollMilliseconds = 0) {
  const [state, setState] = useState({data: null, error: null, loading: true});
  const mounted = useRef(true);
  const load = useCallback(async (silent = false) => {
    if (!silent) setState(current => ({...current, error: null, loading: !current.data}));
    try {
      const data = await projectApi(projectId, '/planning');
      if (mounted.current) setState(current => current.data?.plan?.version > data.plan.version
        ? {...current, error: null, loading: false}
        : {data, error: null, loading: false});
    } catch (error) {
      if (mounted.current) setState(current => ({data: current.data, error, loading: false}));
    }
  }, [projectId]);
  useEffect(() => {
    mounted.current = true;
    load(false);
    const timer = pollMilliseconds ? window.setInterval(() => load(true), pollMilliseconds) : null;
    return () => { mounted.current = false; if (timer) window.clearInterval(timer); };
  }, [load, pollMilliseconds]);
  return {...state, reload: () => load(true)};
}

export function taskHours(task) {
  if (Number(task.remaining_hours) > 0) return Number(task.remaining_hours);
  return Math.max(Number(task.estimated_hours || 0) - Number(task.actual_hours || 0), 0);
}

export function dateOffset(value, start) {
  const day = 86400000;
  return Math.round((Date.parse(value + 'T00:00:00Z') - Date.parse(start + 'T00:00:00Z')) / day);
}
