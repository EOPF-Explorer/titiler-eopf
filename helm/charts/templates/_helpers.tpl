{{/*
Expand the name of the chart.
*/}}
{{- define "titiler-eopf.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "titiler-eopf.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "titiler-eopf.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "titiler-eopf.labels" -}}
helm.sh/chart: {{ include "titiler-eopf.chart" . }}
{{ include "titiler-eopf.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "titiler-eopf.selectorLabels" -}}
app.kubernetes.io/name: {{ include "titiler-eopf.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Environment variables with secret override capability
*/}}
{{- define "titiler-eopf.envVars" -}}
{{- range $key, $val := .Values.env }}
- name: {{ $key }}
  {{- if and $.Values.secrets.secretName (has $key $.Values.secrets.keys) }}
  valueFrom:
    secretKeyRef:
      name: {{ $.Values.secrets.secretName }}
      key: {{ $key }}
  {{- else }}
  value: {{ $val | quote }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
Cache configuration helpers
*/}}
{{- define "titiler-eopf.cache.enabled" -}}
{{- if .Values.cache.enabled -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{- define "titiler-eopf.cache.backend" -}}
{{- .Values.cache.backend | default "redis" -}}
{{- end -}}

{{- define "titiler-eopf.cache.redis.enabled" -}}
{{- if or .Values.cache.redis.internal.enabled .Values.cache.redis.external.enabled -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{/*
Auto-enable redis subchart when cache.redis.internal is enabled
*/}}
{{- define "titiler-eopf.redis.enabled" -}}
{{- if .Values.cache.redis.internal.enabled -}}
{{- if not (hasKey .Values "redis") -}}
{{- $_ := set .Values "redis" (dict "enabled" true) -}}
{{- else -}}
{{- $_ := set .Values "redis" (mergeOverwrite .Values.redis (dict "enabled" true)) -}}
{{- end -}}
{{- end -}}
{{- .Values.redis.enabled | default false -}}
{{- end -}}

{{- define "titiler-eopf.cache.redis.host" -}}
{{- if .Values.cache.redis.internal.enabled -}}
{{- printf "%s-redis-master" .Release.Name -}}
{{- else if .Values.cache.redis.external.enabled -}}
{{- .Values.cache.redis.external.host -}}
{{- end -}}
{{- end -}}

{{- define "titiler-eopf.cache.redis.port" -}}
{{- if .Values.cache.redis.internal.enabled -}}
6379
{{- else if .Values.cache.redis.external.enabled -}}
{{- .Values.cache.redis.external.port | default 6379 -}}
{{- end -}}
{{- end -}}

{{- define "titiler-eopf.cache.s3.enabled" -}}
{{- if .Values.cache.s3.enabled -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}

{{/*
Redis authentication helpers
*/}}
{{- define "titiler-eopf.redis.auth.enabled" -}}
{{- if .Values.cache.redis.internal.enabled -}}
{{- .Values.redis.auth.enabled | default false -}}
{{- else if .Values.cache.redis.external.enabled -}}
{{- .Values.cache.redis.external.auth.enabled | default false -}}
{{- end -}}
{{- end -}}

{{- define "titiler-eopf.redis.auth.secretName" -}}
{{- if .Values.cache.redis.internal.enabled -}}
{{- if .Values.redis.auth.existingSecret -}}
{{- .Values.redis.auth.existingSecret -}}
{{- else -}}
{{- printf "%s-redis" .Release.Name -}}
{{- end -}}
{{- else if .Values.cache.redis.external.enabled -}}
{{- .Values.cache.redis.external.auth.existingSecret -}}
{{- end -}}
{{- end -}}

{{- define "titiler-eopf.redis.auth.secretPasswordKey" -}}
{{- if .Values.cache.redis.internal.enabled -}}
{{- .Values.redis.auth.existingSecretPasswordKey | default "redis-password" -}}
{{- else if .Values.cache.redis.external.enabled -}}
{{- .Values.cache.redis.external.auth.existingSecretKey | default "redis-password" -}}
{{- end -}}
{{- end -}}
