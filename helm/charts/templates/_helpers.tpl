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
Redis specific additions
*/}}
{{- define "titiler-eopf.redis.fullname" -}}
{{- printf "%s-redis" (include "titiler-eopf.fullname" .) -}}
{{- end -}}

{{- define "titiler-eopf.redis.labels" -}}
{{ include "titiler-eopf.labels" . | nindent 0 }}
app.kubernetes.io/component: redis
{{- end -}}

{{- define "titiler-eopf.redis.selectorLabels" -}}
{{ include "titiler-eopf.selectorLabels" . | nindent 0 }}
app.kubernetes.io/component: redis
{{- end -}}
