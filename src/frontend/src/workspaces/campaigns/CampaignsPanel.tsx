import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, DragEvent, FormEvent, KeyboardEvent } from "react";
import {
  ArrowsClockwise,
  ArrowSquareOut,
  Camera,
  ChatCircleText,
  Check,
  Copy,
  FolderOpen,
  ListChecks,
  Megaphone,
  NotePencil,
  PaperPlaneTilt,
  Plus,
  Pulse,
  SpinnerGap,
  Trash,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { apiFetch } from "../../api";
import { compactNumber, humanize, shortDate } from "../../format";
import { campaignStatusConfirmText, shouldApplyGeoSearchResult } from "./helpers";
import type { ClientLeadSource } from "../../types";
import { ConfirmDialog, CtEmptyState } from "../../App";
import type { ConfirmDialogState } from "../../App";

type CampaignsPanelView = "campaigns" | "create";

type CampaignClientItem = {
  id: string;
  display_name: string;
  lead?: {
    full_name?: string | null;
    phone?: string | null;
    email?: string | null;
  } | null;
};

type LeadCaptureCampaignItem = {
  id: string;
  name: string;
  status: string;
  public_url: string;
  public_slug: string;
  client_id: string;
  client?: CampaignClientItem | null;
  submission_count: number;
  daily_budget_usd: number | null;
  location: string;
  campaign_info: Record<string, unknown>;
  meta_plan_graph?: MetaPlanGraph;
  creative_brief: string;
  form_schema: { fields?: CampaignFormField[] };
  delivery_config?: CampaignDeliveryConfig;
  delivery_source?: ClientLeadSource | null;
  delivery_sources?: ClientLeadSource[];
  meta_pixel_id: string;
  meta_event_name: string;
  meta_events_enabled: boolean;
  meta_optimization?: CampaignMetaOptimization;
  created_at: string | null;
  updated_at: string | null;
};

type LeadCaptureSubmissionItem = {
  id: string;
  full_name: string | null;
  phone: string;
  phone_missing?: boolean;
  email: string | null;
  answers: Record<string, unknown>;
  delivery_status: string;
  delivery_statuses?: Array<{
    delivery_id: string;
    source_id: string;
    recipient_name: string;
    recipient_phone: string;
    delivery_status: string;
    last_delivery_error?: string | null;
  }>;
  meta_event_status: string;
  created_at: string | null;
};

type CampaignFormField = {
  id: string;
  label: string;
  type: string;
  required?: boolean;
  placeholder?: string;
  options?: string[];
};

type CampaignFieldDraft = CampaignFormField & {
  optionsText: string;
};
type CampaignPresentationTheme = "default" | "light" | "contrast";
type CampaignPresentationDraft = {
  title: string;
  eyebrow: string;
  trustCue: string;
  submitLabel: string;
  theme: CampaignPresentationTheme;
};

const defaultCampaignPresentation: CampaignPresentationDraft = {
  title: "Consulta",
  eyebrow: "Consulta",
  trustCue: "",
  submitLabel: "Enviar",
  theme: "default",
};

type CampaignClientMode = "existing" | "new";

type CampaignCreativeDraft = {
  primaryText: string;
  headline: string;
  description: string;
  assetBrief: string;
  destinationUrl: string;
  mediaCount: number;
  mediaUrl: string;
  callToAction: string;
};

type CampaignCreativeAssetItem = {
  id: string;
  campaign_id: string;
  client_id: string;
  status: string;
  asset_type: string;
  prompt: string;
  file_path: string;
  dimensions: string;
  source_refs: Array<Record<string, unknown>>;
  media_url: string;
  created_at: string | null;
  updated_at: string | null;
};

type CampaignStoredCreativeMedia = {
  key: string;
  name: string;
  media_url: string;
  asset_type: string;
  source: string;
};

type MetaPlanStrategy = "1x1x3" | "1x3x3" | "3x3x3" | "custom";

type MetaPlanNodeSelection = {
  type: "campaign" | "ad_set" | "ad";
  id: string;
};

type MetaPlanCreativeMedia = {
  creative_asset_id?: string;
  asset_file_path?: string;
  asset_type?: string;
  media_url?: string;
  source?: string;
  meta_creative_id?: string;
  image_hash?: string;
  video_id?: string;
};

type MetaPlanAd = {
  id: string;
  name: string;
  status: string;
  primary_text: string;
  headline: string;
  description: string;
  call_to_action: string;
  destination_url: string;
  media: MetaPlanCreativeMedia[];
};

type MetaPlanAdSet = {
  id: string;
  name: string;
  status: string;
  destination_type: "form" | "website" | "whatsapp";
  page_id?: string;
  instagram_actor_id?: string;
  whatsapp_phone_number_id?: string;
  whatsapp_referral_source_id?: string;
  lead_form_id?: string;
  client_lead_source_id?: string;
  landing_page_url?: string;
  performance_goal: string;
  optimization_goal: string;
  billing_event: string;
  bid_strategy: string;
  budget_daily_usd?: number | null;
  budget_total_usd?: number | null;
  audience: { locations: CampaignGeoLocation[] };
  targeting: Record<string, unknown>;
  ads: MetaPlanAd[];
};

type MetaPlanCampaign = {
  id: string;
  name: string;
  status: string;
  objective: string;
  buying_type: string;
  special_ad_categories: string[];
  budget_daily_usd?: number | null;
  budget_total_usd?: number | null;
  ad_sets: MetaPlanAdSet[];
};

type MetaPlanGraph = {
  schema_version: string;
  strategy: MetaPlanStrategy | string;
  campaigns: MetaPlanCampaign[];
};

type CampaignGeoTargetingDraft = {
  locations: CampaignGeoLocation[];
};

type CampaignGeoArea = {
  name: string;
  key?: string;
  country_code?: string;
  type?: "region" | "city";
  source?: "meta" | "local";
};

type CampaignGeoLocation = {
  country_code: string;
  regions: CampaignGeoArea[];
  cities: CampaignGeoArea[];
};

type CampaignGeoSearchResponse = {
  country_code: string;
  kind: "region";
  query: string;
  source: "meta" | "local";
  meta_error?: string | null;
  suggestions: CampaignGeoArea[];
};

type CampaignMetaDefaults = {
  meta_events_available: boolean;
  meta_event_name: string;
  pixel_source: string;
  pixel_label: string;
};

type CampaignMetaOptimization = {
  enabled: boolean;
  pixel_id?: string;
  event_name?: string;
  custom_event_type?: string;
  optimization_goal?: string;
  billing_event?: string;
  promoted_object?: Record<string, string>;
};

type CampaignDeliveryContact = {
  id: string;
  label: string;
  phone: string;
  kind?: string;
  normalized_phone?: string;
};

type CampaignDeliveryConfig = {
  enabled: boolean;
  contacts: CampaignDeliveryContact[];
};

type CampaignDeliveryPresetsResponse = {
  presets: CampaignDeliveryContact[];
};

const emptyCampaignMetaDefaults: CampaignMetaDefaults = {
  meta_events_available: false,
  meta_event_name: "Lead",
  pixel_source: "",
  pixel_label: "",
};

const campaignFieldTypes = [
  { value: "text", label: "Text" },
  { value: "textarea", label: "Long text" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone" },
  { value: "yes_no", label: "Yes / No" },
  { value: "select", label: "Choice" },
  { value: "multi_select", label: "Multiple" },
];

const campaignClientDeliveryPreset: CampaignDeliveryContact = { id: "client", label: "Cliente", phone: "", kind: "client" };

const campaignCountryOptions = [
  { value: "AR", label: "Argentina" },
  { value: "DE", label: "Alemania" },
  { value: "BO", label: "Bolivia" },
  { value: "CL", label: "Chile" },
  { value: "CO", label: "Colombia" },
  { value: "EC", label: "Ecuador" },
  { value: "ES", label: "Espana" },
  { value: "US", label: "Estados Unidos" },
  { value: "MX", label: "Mexico" },
  { value: "PY", label: "Paraguay" },
  { value: "PE", label: "Peru" },
  { value: "UY", label: "Uruguay" },
];
const campaignCountryLabels = Object.fromEntries(campaignCountryOptions.map((country) => [country.value, country.label]));
const campaignGeoNamePattern = /^[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9 .,'()/-]{0,95}$/;
type CampaignTargetStep = "country" | "province";

function defaultCampaignFields(): CampaignFieldDraft[] {
  return [
    { id: "full_name", label: "Cual es tu nombre?", type: "text", required: true, placeholder: "Nombre completo", optionsText: "" },
    { id: "phone", label: "Cual es tu numero de WhatsApp?", type: "phone", required: true, placeholder: "+54 9 ...", optionsText: "" },
    { id: "email", label: "Cual es tu email?", type: "email", required: false, placeholder: "nombre@email.com", optionsText: "" },
    { id: "necesidad", label: "Que servicio necesitas?", type: "textarea", required: true, placeholder: "Contanos brevemente", optionsText: "" },
  ];
}

function campaignDeliveryConfigOrDefault(campaign: LeadCaptureCampaignItem | null): CampaignDeliveryConfig {
  const config = campaign?.delivery_config;
  if (config && Array.isArray(config.contacts)) {
    return {
      enabled: config.enabled !== false,
      contacts: config.contacts,
    };
  }
  return { enabled: true, contacts: [campaignClientDeliveryPreset] };
}

function campaignDeliveryContactSelected(config: CampaignDeliveryConfig, contactId: string): boolean {
  return config.contacts.some((contact) => contact.id === contactId);
}

function campaignClientDeliveryContact(client: CampaignClientItem | null | undefined): CampaignDeliveryContact {
  return {
    id: "client",
    label: client?.display_name || client?.lead?.full_name || "Cliente",
    phone: client?.lead?.phone || "",
    kind: "client",
  };
}

function campaignDeliveryDisplayContact(contact: CampaignDeliveryContact, client: CampaignClientItem | null | undefined): CampaignDeliveryContact {
  return contact.id === "client" || contact.kind === "client"
    ? campaignClientDeliveryContact(client)
    : contact;
}

function campaignDeliverySuggestionContacts(
  client: CampaignClientItem | null | undefined,
  config: CampaignDeliveryConfig,
  presets: CampaignDeliveryContact[],
): CampaignDeliveryContact[] {
  const suggestions = [campaignClientDeliveryContact(client), ...presets.filter((contact) => contact.id !== "client")];
  return suggestions.filter((contact) => !campaignDeliveryContactSelected(config, contact.id));
}

function campaignDeliveryContactPhoneLabel(contact: CampaignDeliveryContact): string {
  if (contact.phone) {
    return contact.phone;
  }
  return contact.id === "client" || contact.kind === "client" ? "Cliente asociado" : "Sin WhatsApp";
}

function campaignDeliveryConfigPayload(config: CampaignDeliveryConfig): CampaignDeliveryConfig {
  return {
    enabled: config.enabled,
    contacts: config.contacts.map((contact) => ({
      id: contact.id,
      label: contact.label,
      phone: contact.phone,
      kind: contact.kind || "custom",
    })),
  };
}

function campaignFieldId(value: string, index: number): string {
  const normalized = value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  return normalized || `field_${index + 1}`;
}

function campaignFormSchema(fields: CampaignFieldDraft[]): { fields: CampaignFormField[]; layout: string } {
  return {
    layout: "multi_step",
    fields: fields.map((field, index) => {
      const options = field.optionsText
        .split(/[\n,]/)
        .map((option) => option.trim())
        .filter(Boolean);
      return {
        id: campaignFieldId(field.id || field.label, index),
        label: field.label.trim() || `Field ${index + 1}`,
        type: field.type,
        required: Boolean(field.required),
        placeholder: field.placeholder?.trim() || "",
        options,
      };
    }),
  };
}

function campaignPresentationPayload(draft: CampaignPresentationDraft): Record<string, string> {
  const theme = ["default", "light", "contrast"].includes(draft.theme) ? draft.theme : "default";
  return {
    title: cleanCampaignPresentationText(draft.title, 80) || "Consulta",
    eyebrow: cleanCampaignPresentationText(draft.eyebrow, 40) || "Consulta",
    trust_cue: cleanCampaignPresentationText(draft.trustCue, 120),
    submit_label: cleanCampaignPresentationText(draft.submitLabel, 40) || "Enviar",
    theme,
  };
}

function cleanCampaignPresentationText(value: string, limit: number): string {
  return value.replace(/[<>]/g, "").replace(/\s+/g, " ").trim().slice(0, limit);
}

function campaignSubmissionPhoneLabel(submission: LeadCaptureSubmissionItem): string {
  if (submission.phone_missing || submission.phone.startsWith("0000")) {
    return "Sin WhatsApp";
  }
  return submission.phone || "-";
}

function validateCampaignGeoAreas(areas: CampaignGeoArea[], label: string): string | null {
  if (areas.length > 20) {
    return `${label} supports up to 20 values.`;
  }
  const seen = new Set<string>();
  for (const area of areas) {
    const name = area.name.trim();
    if (!campaignGeoNamePattern.test(name)) {
      return `${label} has invalid characters: ${name}`;
    }
    const key = name.toLowerCase();
    if (seen.has(key)) {
      return `${label} has a duplicate value: ${name}`;
    }
    seen.add(key);
  }
  return null;
}

function campaignGeoLocationLabel(location: CampaignGeoLocation): string {
  const parts = [campaignCountryLabels[location.country_code] || location.country_code];
  if (location.regions.length) {
    parts.push(location.regions.map((area) => area.name).join(", "));
  }
  if (location.cities.length) {
    parts.push(location.cities.map((area) => area.name).join(", "));
  }
  return parts.join(" · ");
}

function validateCampaignGeoLocations(locations: CampaignGeoLocation[]): string | null {
  if (locations.length > 20) {
    return "Locations supports up to 20 values.";
  }
  const seen = new Set<string>();
  for (const location of locations) {
    const regionError = validateCampaignGeoAreas(location.regions, "Regions / provinces");
    if (regionError) {
      return regionError;
    }
    const duplicateKey = JSON.stringify({
      country_code: location.country_code,
      regions: location.regions.map((area) => area.key || area.name.toLowerCase()).sort(),
    });
    if (seen.has(duplicateKey)) {
      return `Duplicate location: ${campaignGeoLocationLabel(location)}`;
    }
    seen.add(duplicateKey);
  }
  return null;
}

function campaignGeoTargeting(locations: CampaignGeoLocation[]): CampaignGeoTargetingDraft {
  const cleanAreas = (areas: CampaignGeoArea[], country: string) => areas.map((area) => ({
    name: area.name.trim(),
    ...(area.key ? { key: area.key } : {}),
    country_code: area.country_code || country,
  }));
  return {
    locations: locations.map((location) => {
      const country = location.country_code.trim().toUpperCase() || "AR";
      return {
        country_code: country,
        regions: cleanAreas(location.regions, country),
        cities: cleanAreas(location.cities, country),
      };
    }),
  };
}

function campaignClientLabel(client: CampaignClientItem): string {
  const lead = client.lead;
  return [
    client.display_name || lead?.full_name || client.id,
    lead?.phone,
    lead?.email,
  ].filter(Boolean).join(" · ");
}

function campaignLocationKindLabel(location: CampaignGeoLocation): string {
  if (location.regions.length) {
    return "Provincia";
  }
  return "Pais";
}

function campaignLocationDetailLabel(location: CampaignGeoLocation): string {
  return location.regions.length ? location.regions.map((area) => area.name).join(", ") : "Pais entero";
}

function campaignLocationButtonLabel(location: CampaignGeoLocation): string {
  const country = campaignCountryLabels[location.country_code] || location.country_code;
  if (!location.regions.length) {
    return country;
  }
  return `${country} · ${location.regions[0].name}`;
}

function filteredCampaignCountries(query: string) {
  const cleanQuery = query.trim().toLowerCase();
  if (!cleanQuery) {
    return campaignCountryOptions;
  }
  return campaignCountryOptions.filter((country) => {
    const haystack = `${country.label} ${country.value}`.toLowerCase();
    return haystack.includes(cleanQuery);
  });
}

function campaignCreativeBriefSummary(creative: CampaignCreativeDraft): string {
  const creativeLines = [
    creative.primaryText.trim() ? `Primary text: ${creative.primaryText.trim()}` : "",
    creative.headline.trim() ? `Headline: ${creative.headline.trim()}` : "",
    creative.description.trim() ? `Description: ${creative.description.trim()}` : "",
    creative.assetBrief.trim() ? `Creative asset: ${creative.assetBrief.trim()}` : "",
    creative.mediaCount ? `Media files: ${creative.mediaCount}` : "",
    creative.mediaUrl.trim() ? `Media URL: ${creative.mediaUrl.trim()}` : "",
    creative.destinationUrl.trim() ? `Destination URL: ${creative.destinationUrl.trim()}` : "",
  ].filter(Boolean);
  if (!creativeLines.length) {
    return "";
  }
  if (creative.callToAction.trim()) {
    creativeLines.push(`Call to action: ${creative.callToAction.trim()}`);
  }
  return creativeLines.join("\n");
}

function campaignCreativeAssetName(asset: CampaignCreativeAssetItem): string {
  const uploadRef = asset.source_refs.find((item) => typeof item.original_filename === "string");
  const originalFilename = uploadRef?.original_filename;
  if (typeof originalFilename === "string" && originalFilename.trim()) {
    return originalFilename.trim();
  }
  return asset.file_path.split("/").pop() || asset.id;
}

function campaignCreativeAssetPayload(asset: CampaignCreativeAssetItem): Record<string, string> {
  return {
    creative_asset_id: asset.id,
    asset_file_path: asset.file_path,
    asset_type: asset.asset_type,
    media_url: asset.media_url,
  };
}

const metaPlanStrategies: Array<{ value: MetaPlanStrategy; label: string; campaignCount: number; adSetCount: number; adCount: number }> = [
  { value: "1x1x3", label: "1 > 1 > 3", campaignCount: 1, adSetCount: 1, adCount: 3 },
  { value: "1x3x3", label: "1 > 3 > 3", campaignCount: 1, adSetCount: 3, adCount: 3 },
  { value: "3x3x3", label: "3 > 3 > 3", campaignCount: 3, adSetCount: 3, adCount: 3 },
  { value: "custom", label: "Custom", campaignCount: 1, adSetCount: 1, adCount: 1 },
];

function metaPlanNodeId(prefix: string, index: number): string {
  return `${prefix}_${index + 1}`;
}

function campaignMetaPlanMedia(assets: CampaignCreativeAssetItem[], mediaUrl: string): MetaPlanCreativeMedia[] {
  const uploaded = assets.map((asset) => campaignCreativeAssetPayload(asset));
  const external = mediaUrl.trim() ? [{ source: "external_url", media_url: mediaUrl.trim(), asset_type: campaignMediaType(mediaUrl) }] : [];
  return [...uploaded, ...external];
}

function campaignMetaTargeting(locations: CampaignGeoLocation[]): Record<string, unknown> {
  const countries: string[] = [];
  const regions: Array<Record<string, string>> = [];
  locations.forEach((location) => {
    const country = location.country_code.trim().toUpperCase() || "AR";
    if (!location.regions.length) {
      countries.push(country);
      return;
    }
    location.regions.forEach((region) => {
      regions.push({
        name: region.name,
        country,
        ...(region.key ? { key: region.key } : {}),
      });
    });
  });
  const geoLocations: Record<string, unknown> = {};
  if (countries.length) {
    geoLocations.countries = Array.from(new Set(countries));
  }
  if (regions.length) {
    geoLocations.regions = regions;
  }
  return Object.keys(geoLocations).length ? { geo_locations: geoLocations } : {};
}

function campaignMetaPlanAd(
  id: string,
  name: string,
  creative: CampaignCreativeDraft,
  media: MetaPlanCreativeMedia[],
): MetaPlanAd {
  return {
    id,
    name,
    status: "PAUSED",
    primary_text: creative.primaryText.trim(),
    headline: creative.headline.trim(),
    description: creative.description.trim(),
    call_to_action: creative.callToAction.trim() || "LEARN_MORE",
    destination_url: creative.destinationUrl.trim(),
    media,
  };
}

function campaignMetaPlanGraphFromStrategy({
  strategy,
  campaignName,
  dailyBudget,
  locations,
  creative,
  media,
}: {
  strategy: MetaPlanStrategy;
  campaignName: string;
  dailyBudget: string;
  locations: CampaignGeoLocation[];
  creative: CampaignCreativeDraft;
  media: MetaPlanCreativeMedia[];
}): MetaPlanGraph {
  const shape = metaPlanStrategies.find((item) => item.value === strategy) ?? metaPlanStrategies[0];
  const budget = dailyBudget ? Number(dailyBudget) : null;
  const name = campaignName.trim() || "Nueva campaña";
  const safeLocations = locations.length ? locations : [{ country_code: "AR", regions: [], cities: [] }];
  return {
    schema_version: "konecta.meta_plan_graph.v1",
    strategy,
    campaigns: Array.from({ length: shape.campaignCount }, (_, campaignIndex) => {
      const campaignId = metaPlanNodeId("campaign", campaignIndex);
      return {
        id: campaignId,
        name: shape.campaignCount === 1 ? name : `${name} ${campaignIndex + 1}`,
        status: "PAUSED",
        objective: "OUTCOME_LEADS",
        buying_type: "AUCTION",
        special_ad_categories: [],
        budget_daily_usd: budget,
        budget_total_usd: null,
        ad_sets: Array.from({ length: shape.adSetCount }, (_, adSetIndex) => {
          const adSetId = `${campaignId}_adset_${adSetIndex + 1}`;
          return {
            id: adSetId,
            name: `Ad set ${adSetIndex + 1}`,
            status: "PAUSED",
            destination_type: "form",
            performance_goal: "LEAD_GENERATION",
            optimization_goal: "LEAD_GENERATION",
            billing_event: "IMPRESSIONS",
            bid_strategy: "LOWEST_COST_WITHOUT_CAP",
            budget_daily_usd: null,
            budget_total_usd: null,
            audience: { locations: safeLocations },
            targeting: campaignMetaTargeting(safeLocations),
            ads: Array.from({ length: shape.adCount }, (_, adIndex) => campaignMetaPlanAd(
              `${adSetId}_ad_${adIndex + 1}`,
              `Ad ${adIndex + 1}`,
              creative,
              media,
            )),
          };
        }),
      };
    }),
  };
}

function campaignMetaPlanSelection(graph: MetaPlanGraph): MetaPlanNodeSelection {
  const campaign = graph.campaigns[0];
  const adSet = campaign?.ad_sets[0];
  const ad = adSet?.ads[0];
  if (ad) {
    return { type: "ad", id: ad.id };
  }
  if (adSet) {
    return { type: "ad_set", id: adSet.id };
  }
  return { type: "campaign", id: campaign?.id || "campaign_1" };
}

function campaignMetaPlanCounts(graph: MetaPlanGraph): { campaigns: number; adSets: number; ads: number } {
  const adSets = graph.campaigns.reduce((total, campaign) => total + campaign.ad_sets.length, 0);
  const ads = graph.campaigns.reduce(
    (total, campaign) => total + campaign.ad_sets.reduce((adTotal, adSet) => adTotal + adSet.ads.length, 0),
    0,
  );
  return { campaigns: graph.campaigns.length, adSets, ads };
}

function campaignMetaPlanHydrated(
  graph: MetaPlanGraph,
  {
    campaignName,
    dailyBudget,
    locations,
    creative,
    media,
  }: {
    campaignName: string;
    dailyBudget: string;
    locations: CampaignGeoLocation[];
    creative: CampaignCreativeDraft;
    media: MetaPlanCreativeMedia[];
  },
): MetaPlanGraph {
  const safeLocations = locations.length ? locations : [{ country_code: "AR", regions: [], cities: [] }];
  const budget = dailyBudget ? Number(dailyBudget) : null;
  return {
    ...graph,
    campaigns: graph.campaigns.map((campaign, campaignIndex) => ({
      ...campaign,
      name: campaign.name.trim() || (campaignIndex === 0 ? campaignName.trim() || "Nueva campaña" : `Campaña ${campaignIndex + 1}`),
      budget_daily_usd: campaign.budget_daily_usd || budget,
      ad_sets: campaign.ad_sets.map((adSet) => ({
        ...adSet,
        audience: { locations: safeLocations },
        targeting: campaignMetaTargeting(safeLocations),
        ads: adSet.ads.map((ad) => ({
          ...ad,
          primary_text: ad.primary_text.trim() || creative.primaryText.trim(),
          headline: ad.headline.trim() || creative.headline.trim(),
          description: ad.description.trim() || creative.description.trim(),
          call_to_action: ad.call_to_action.trim() || creative.callToAction.trim() || "LEARN_MORE",
          destination_url: ad.destination_url.trim() || creative.destinationUrl.trim(),
          media: ad.media.length ? ad.media : media,
        })),
      })),
    })),
  };
}

function selectedMetaCampaign(graph: MetaPlanGraph, selection: MetaPlanNodeSelection): MetaPlanCampaign | null {
  return graph.campaigns.find((campaign) => campaign.id === selection.id) ?? null;
}

function selectedMetaAdSet(graph: MetaPlanGraph, selection: MetaPlanNodeSelection): MetaPlanAdSet | null {
  for (const campaign of graph.campaigns) {
    const adSet = campaign.ad_sets.find((item) => item.id === selection.id);
    if (adSet) {
      return adSet;
    }
  }
  return null;
}

function selectedMetaAd(graph: MetaPlanGraph, selection: MetaPlanNodeSelection): MetaPlanAd | null {
  for (const campaign of graph.campaigns) {
    for (const adSet of campaign.ad_sets) {
      const ad = adSet.ads.find((item) => item.id === selection.id);
      if (ad) {
        return ad;
      }
    }
  }
  return null;
}

function campaignRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function campaignString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function campaignMediaType(value: string, fallback: string = "image"): string {
  const cleanValue = value.toLowerCase();
  if (fallback.toLowerCase().includes("video") || /\.(mov|mp4|webm)(\?|#|$)/i.test(cleanValue)) {
    return "video";
  }
  if (fallback.toLowerCase().includes("image") || /\.(avif|gif|heic|jpeg|jpg|png|webp)(\?|#|$)/i.test(cleanValue)) {
    return "image";
  }
  return fallback || "image";
}

function campaignMediaName(media: Record<string, unknown>, fallbackIndex: number): string {
  const refs = Array.isArray(media.source_refs) ? media.source_refs : [];
  const uploadRef = refs.find((item) => campaignRecord(item)?.original_filename);
  const originalFilename = campaignString(campaignRecord(uploadRef)?.original_filename);
  if (originalFilename) {
    return originalFilename;
  }
  const filePath = campaignString(media.asset_file_path) || campaignString(media.file_path);
  if (filePath) {
    return filePath.split("/").filter(Boolean).pop() || filePath;
  }
  const mediaUrl = campaignString(media.media_url);
  if (mediaUrl) {
    return mediaUrl.split(/[/?#]/).filter(Boolean).pop() || `Ad media ${fallbackIndex + 1}`;
  }
  return `Ad media ${fallbackIndex + 1}`;
}

function campaignStoredCreativeMedia(campaign: LeadCaptureCampaignItem | null): CampaignStoredCreativeMedia[] {
  const campaignInfo = campaignRecord(campaign?.campaign_info);
  const creative = campaignRecord(campaignInfo?.creative);
  const rawMedia = Array.isArray(creative?.media) ? creative.media : [];
  const mediaRows = rawMedia
    .map((item, index) => {
      const media = campaignRecord(item);
      if (!media) {
        return null;
      }
      const mediaUrl = campaignString(media.media_url);
      const assetId = campaignString(media.creative_asset_id);
      const assetPath = campaignString(media.asset_file_path);
      const source = campaignString(media.source) || (assetId ? "upload" : "url");
      const assetType = campaignMediaType(mediaUrl || assetPath, campaignString(media.asset_type));
      return {
        key: assetId || assetPath || mediaUrl || `media-${index}`,
        name: campaignMediaName(media, index),
        media_url: mediaUrl,
        asset_type: assetType,
        source,
      };
    })
    .filter((item): item is CampaignStoredCreativeMedia => Boolean(item));

  const primaryMediaUrl = campaignString(creative?.primary_media_url);
  if (primaryMediaUrl && !mediaRows.some((item) => item.media_url === primaryMediaUrl)) {
    mediaRows.unshift({
      key: primaryMediaUrl,
      name: primaryMediaUrl.split(/[/?#]/).filter(Boolean).pop() || "Primary media",
      media_url: primaryMediaUrl,
      asset_type: campaignMediaType(primaryMediaUrl),
      source: "primary",
    });
  }
  return mediaRows;
}

function campaignCreativeFileAllowed(file: File): boolean {
  const type = file.type.toLowerCase();
  if (type.startsWith("image/") || type.startsWith("video/")) {
    return true;
  }
  return /\.(avif|gif|heic|jpeg|jpg|mov|mp4|png|webm|webp)$/i.test(file.name);
}

function CampaignProvinceSearch({
  countryCode,
  query,
  onQueryChange,
  onPick,
  onError,
}: {
  countryCode: string;
  query: string;
  onQueryChange: (next: string) => void;
  onPick: (area: CampaignGeoArea) => void;
  onError: (message: string) => void;
}) {
  const [suggestions, setSuggestions] = useState<CampaignGeoArea[]>([]);
  const [loading, setLoading] = useState(false);
  const searchRequestId = useRef(0);

  useEffect(() => {
    const cleanQuery = query.trim();
    const requestId = searchRequestId.current + 1;
    searchRequestId.current = requestId;
    if (!cleanQuery) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setSuggestions([]);
    setLoading(true);
    const timeout = window.setTimeout(async () => {
      try {
        const payload = await apiFetch<CampaignGeoSearchResponse>(
          `/api/campaigns/geo/search?country_code=${encodeURIComponent(countryCode)}&kind=region&q=${encodeURIComponent(cleanQuery)}&limit=12`,
        );
        if (shouldApplyGeoSearchResult(requestId, searchRequestId.current)) {
          setSuggestions(payload.suggestions ?? []);
        }
      } catch (reason) {
        if (shouldApplyGeoSearchResult(requestId, searchRequestId.current)) {
          setSuggestions([]);
          onError(reason instanceof Error ? reason.message : "No se pudo buscar provincia.");
        }
      } finally {
        if (shouldApplyGeoSearchResult(requestId, searchRequestId.current)) {
          setLoading(false);
        }
      }
    }, 220);
    return () => window.clearTimeout(timeout);
  }, [countryCode, onError, query]);

  function addFirstSuggestion(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    if (suggestions[0]) {
      onPick(suggestions[0]);
    }
  }

  return (
    <div className="campaign-target-search">
      <div className="campaign-command-input">
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={addFirstSuggestion}
          placeholder="Buscar provincia"
        />
        {loading ? <SpinnerGap size={14} weight="bold" className="workstation-spinner" /> : null}
      </div>
      {!loading && suggestions.length ? (
        <div className="campaign-target-results">
          {suggestions.map((area) => (
            <button type="button" key={`${area.source || "local"}-${area.key || area.name}`} onClick={() => onPick(area)}>
              <span>{area.name}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function CampaignsPanel({ refreshSignal, onError }: { refreshSignal: number; onError: (message: string) => void }) {
  const [campaigns, setCampaigns] = useState<LeadCaptureCampaignItem[]>([]);
  const [clients, setClients] = useState<CampaignClientItem[]>([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [submissions, setSubmissions] = useState<LeadCaptureSubmissionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [submissionsLoading, setSubmissionsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [campaignView, setCampaignView] = useState<CampaignsPanelView>("campaigns");
  const [campaignName, setCampaignName] = useState("");
  const [campaignStatus, setCampaignStatus] = useState("draft");
  const [clientMode, setClientMode] = useState<CampaignClientMode>("new");
  const [existingClientId, setExistingClientId] = useState("");
  const [newClientName, setNewClientName] = useState("");
  const [newClientWhatsapp, setNewClientWhatsapp] = useState("");
  const [newClientEmail, setNewClientEmail] = useState("");
  const [newClientExtraInfo, setNewClientExtraInfo] = useState("");
  const [dailyBudget, setDailyBudget] = useState("");
  const [campaignLocations, setCampaignLocations] = useState<CampaignGeoLocation[]>([]);
  const [targetStep, setTargetStep] = useState<CampaignTargetStep>("country");
  const [countryQuery, setCountryQuery] = useState("");
  const [draftCountryCode, setDraftCountryCode] = useState("");
  const [provinceQuery, setProvinceQuery] = useState("");
  const [creativeBrief, setCreativeBrief] = useState("");
  const [creativeHeadline, setCreativeHeadline] = useState("");
  const [creativeDescription, setCreativeDescription] = useState("");
  const [creativeAssetBrief, setCreativeAssetBrief] = useState("");
  const [creativeAssets, setCreativeAssets] = useState<CampaignCreativeAssetItem[]>([]);
  const [creativeMediaUrl, setCreativeMediaUrl] = useState("");
  const [creativeMediaUploading, setCreativeMediaUploading] = useState(false);
  const [creativeMediaDropActive, setCreativeMediaDropActive] = useState(false);
  const [destinationUrl, setDestinationUrl] = useState("");
  const [metaEventsEnabled, setMetaEventsEnabled] = useState(false);
  const [metaOptimizeForPixel, setMetaOptimizeForPixel] = useState(false);
  const [metaDefaults, setMetaDefaults] = useState<CampaignMetaDefaults>(emptyCampaignMetaDefaults);
  const [metaDefaultsError, setMetaDefaultsError] = useState("");
  const [campaignDeliveryPresets, setCampaignDeliveryPresets] = useState<CampaignDeliveryContact[]>([]);
  const [deliveryEnabled, setDeliveryEnabled] = useState(true);
  const [deliveryContactIds, setDeliveryContactIds] = useState<string[]>(["client"]);
  const [deliveryCustomContacts, setDeliveryCustomContacts] = useState<CampaignDeliveryContact[]>([]);
  const [deliveryCustomName, setDeliveryCustomName] = useState("");
  const [deliveryCustomPhone, setDeliveryCustomPhone] = useState("");
  const [showCreateDeliveryAdd, setShowCreateDeliveryAdd] = useState(false);
  const [detailDeliveryName, setDetailDeliveryName] = useState("");
  const [detailDeliveryPhone, setDetailDeliveryPhone] = useState("");
  const [showDetailDeliveryAdd, setShowDetailDeliveryAdd] = useState(false);
  const [fields, setFields] = useState<CampaignFieldDraft[]>(defaultCampaignFields);
  const [presentation, setPresentation] = useState<CampaignPresentationDraft>(defaultCampaignPresentation);
  const [metaPlanStrategy, setMetaPlanStrategy] = useState<MetaPlanStrategy>("1x1x3");
  const [metaPlanGraph, setMetaPlanGraph] = useState<MetaPlanGraph>(() => campaignMetaPlanGraphFromStrategy({
    strategy: "1x1x3",
    campaignName: "",
    dailyBudget: "",
    locations: [],
    creative: {
      primaryText: "",
      headline: "",
      description: "",
      assetBrief: "",
      destinationUrl: "",
      mediaCount: 0,
      mediaUrl: "",
      callToAction: "LEARN_MORE",
    },
    media: [],
  }));
  const [selectedMetaNode, setSelectedMetaNode] = useState<MetaPlanNodeSelection>(() => campaignMetaPlanSelection(metaPlanGraph));
  const [campaignConfirmDialog, setCampaignConfirmDialog] = useState<ConfirmDialogState | null>(null);
  const campaignLoadRequestId = useRef(0);
  const campaignSubmissionsRequestId = useRef(0);
  const selectedCampaignIdRef = useRef<string | null>(selectedCampaignId);

  const activeCampaignCount = campaigns.filter((campaign) => campaign.status === "active").length;
  const hasCampaigns = campaigns.length > 0;
  const isCreateView = campaignView === "create";
  const showCampaignEmpty = !loading && !hasCampaigns;
  const selectedCampaign = campaigns.find((campaign) => campaign.id === selectedCampaignId) ?? campaigns[0] ?? null;
  const selectedClient = clients.find((client) => client.id === existingClientId) ?? null;
  const selectedCampaignDelivery = campaignDeliveryConfigOrDefault(selectedCampaign);
  const createDeliveryClient = clientMode === "existing"
    ? selectedClient
    : {
      id: "new-client",
      display_name: newClientName.trim() || "Cliente",
      lead: {
        full_name: newClientName.trim() || null,
        phone: newClientWhatsapp.trim() || null,
        email: newClientEmail.trim() || null,
      },
    };
  const createDeliveryConfig = buildCreateDeliveryConfig();
  const createDeliverySuggestions = campaignDeliverySuggestionContacts(createDeliveryClient, createDeliveryConfig, campaignDeliveryPresets);
  const selectedCampaignDeliverySuggestions = campaignDeliverySuggestionContacts(selectedCampaign?.client, selectedCampaignDelivery, campaignDeliveryPresets);
  const selectedCampaignMedia = campaignStoredCreativeMedia(selectedCampaign);
  const countryMatches = filteredCampaignCountries(countryQuery);
  const draftCountryLabel = draftCountryCode ? campaignCountryLabels[draftCountryCode] || draftCountryCode : "";
  const creativeDraft: CampaignCreativeDraft = {
    primaryText: creativeBrief,
    headline: creativeHeadline,
    description: creativeDescription,
    assetBrief: creativeAssetBrief,
    destinationUrl,
    mediaCount: creativeAssets.length,
    mediaUrl: creativeMediaUrl,
    callToAction: "LEARN_MORE",
  };
  const creativeMedia = campaignMetaPlanMedia(creativeAssets, creativeMediaUrl);
  const creativeSummary = campaignCreativeBriefSummary(creativeDraft);
  const metaPlanCounts = campaignMetaPlanCounts(metaPlanGraph);
  const selectedGraphCampaign = selectedMetaCampaign(metaPlanGraph, selectedMetaNode);
  const selectedGraphAdSet = selectedMetaAdSet(metaPlanGraph, selectedMetaNode);
  const selectedGraphAd = selectedMetaAd(metaPlanGraph, selectedMetaNode);
  const campaignCreateDraftDirty = Boolean(
    campaignName.trim()
    || campaignStatus !== "draft"
    || clientMode !== "new"
    || existingClientId
    || newClientName.trim()
    || newClientWhatsapp.trim()
    || newClientEmail.trim()
    || newClientExtraInfo.trim()
    || dailyBudget.trim()
    || campaignLocations.length
    || countryQuery.trim()
    || draftCountryCode
    || provinceQuery.trim()
    || creativeBrief.trim()
    || creativeHeadline.trim()
    || creativeDescription.trim()
    || creativeAssetBrief.trim()
    || creativeAssets.length
    || creativeMediaUrl.trim()
    || destinationUrl.trim()
    || metaEventsEnabled !== Boolean(metaDefaults.meta_events_available)
    || metaOptimizeForPixel !== Boolean(metaDefaults.meta_events_available)
    || deliveryEnabled !== true
    || deliveryContactIds.length !== 1
    || deliveryContactIds[0] !== "client"
    || deliveryCustomContacts.length
    || deliveryCustomName.trim()
    || deliveryCustomPhone.trim()
    || showCreateDeliveryAdd
    || JSON.stringify(fields) !== JSON.stringify(defaultCampaignFields())
    || JSON.stringify(presentation) !== JSON.stringify(defaultCampaignPresentation)
    || metaPlanStrategy !== "1x1x3"
  );

  useEffect(() => {
    selectedCampaignIdRef.current = selectedCampaignId;
  }, [selectedCampaignId]);

  async function loadCampaignSubmissions(campaignId: string) {
    const requestId = campaignSubmissionsRequestId.current + 1;
    campaignSubmissionsRequestId.current = requestId;
    setSubmissionsLoading(true);
    try {
      const payload = await apiFetch<{ submissions: LeadCaptureSubmissionItem[] }>(
        `/api/campaigns/${encodeURIComponent(campaignId)}/submissions?limit=20`,
      );
      if (campaignSubmissionsRequestId.current === requestId && selectedCampaignIdRef.current === campaignId) {
        setSubmissions(payload.submissions ?? []);
      }
    } finally {
      if (campaignSubmissionsRequestId.current === requestId) {
        setSubmissionsLoading(false);
      }
    }
  }

  async function uploadCampaignCreativeFile(file: File) {
    if (!campaignCreativeFileAllowed(file)) {
      onError("Upload an image or video file for the ad creative.");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("client_id", clientMode === "existing" ? existingClientId : "");
    form.append("prompt", creativeAssetBrief.trim() || creativeBrief.trim());
    setCreativeMediaUploading(true);
    try {
      const asset = await apiFetch<CampaignCreativeAssetItem>("/api/platform/creative-assets/upload", {
        method: "POST",
        body: form,
      });
      setCreativeAssets((current) => {
        if (current.some((item) => item.id === asset.id)) {
          return current;
        }
        return [...current, asset];
      });
      if (selectedMetaNode.type === "ad") {
        const media = campaignCreativeAssetPayload(asset);
        updateMetaPlanAd(selectedMetaNode.id, {
          media: [...(selectedGraphAd?.media ?? []), media],
        });
      }
      if (!creativeAssetBrief.trim()) {
        setCreativeAssetBrief(campaignCreativeAssetName(asset));
      }
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not upload creative media.");
    } finally {
      setCreativeMediaUploading(false);
    }
  }

  async function uploadCampaignCreativeFiles(files: File[]) {
    const usableFiles = files.filter((file) => file.size > 0);
    if (!usableFiles.length) {
      return;
    }
    for (const file of usableFiles) {
      await uploadCampaignCreativeFile(file);
    }
  }

  function campaignCreativeFilesFromClipboard(event: ClipboardEvent<HTMLElement>): File[] {
    const directFiles = Array.from(event.clipboardData.files).filter((file) => file.size > 0);
    if (directFiles.length) {
      return directFiles;
    }
    const files: File[] = [];
    for (const item of Array.from(event.clipboardData.items)) {
      const pastedFile = item.kind === "file" ? item.getAsFile() : null;
      if (pastedFile && pastedFile.size > 0) {
        files.push(pastedFile);
      }
    }
    return files;
  }

  function handleCampaignCreativeDragOver(event: DragEvent<HTMLElement>) {
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = creativeMediaUploading ? "none" : "copy";
    setCreativeMediaDropActive(true);
  }

  function handleCampaignCreativeDragLeave(event: DragEvent<HTMLElement>) {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
      return;
    }
    setCreativeMediaDropActive(false);
  }

  function handleCampaignCreativeDrop(event: DragEvent<HTMLElement>) {
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    setCreativeMediaDropActive(false);
    if (creativeMediaUploading) {
      return;
    }
    void uploadCampaignCreativeFiles(Array.from(event.dataTransfer.files));
  }

  function handleCampaignCreativePaste(event: ClipboardEvent<HTMLElement>) {
    const files = campaignCreativeFilesFromClipboard(event);
    if (!files.length || creativeMediaUploading) {
      return;
    }
    event.preventDefault();
    void uploadCampaignCreativeFiles(files);
  }

  function removeCampaignCreativeAsset(assetId: string) {
    setCreativeAssets((current) => current.filter((asset) => asset.id !== assetId));
    setMetaPlanGraph((current) => ({
      ...current,
      campaigns: current.campaigns.map((campaign) => ({
        ...campaign,
        ad_sets: campaign.ad_sets.map((adSet) => ({
          ...adSet,
          ads: adSet.ads.map((ad) => ({
            ...ad,
            media: ad.media.filter((media) => media.creative_asset_id !== assetId),
          })),
        })),
      })),
    }));
  }

  async function loadCampaigns() {
    const requestId = campaignLoadRequestId.current + 1;
    campaignLoadRequestId.current = requestId;
    setLoading(true);
    try {
      const [campaignPayload, clientPayload, metaDefaultsResult, deliveryPresetsResult] = await Promise.all([
        apiFetch<{ campaigns: LeadCaptureCampaignItem[] }>("/api/campaigns?limit=120"),
        apiFetch<{ clients: CampaignClientItem[] }>("/api/campaigns/clients?limit=300"),
        apiFetch<CampaignMetaDefaults>("/api/campaigns/meta/defaults")
          .then((payload) => ({ payload, error: "" }))
          .catch((reason) => ({
            payload: emptyCampaignMetaDefaults,
            error: reason instanceof Error ? reason.message : "Could not load Meta defaults.",
          })),
        apiFetch<CampaignDeliveryPresetsResponse>("/api/campaigns/delivery/presets")
          .then((payload) => ({ payload, error: "" }))
          .catch((reason) => ({
            payload: { presets: [] },
            error: reason instanceof Error ? reason.message : "Could not load Delivery presets.",
          })),
      ]);
      if (campaignLoadRequestId.current !== requestId) {
        return;
      }
      const nextCampaigns = campaignPayload.campaigns ?? [];
      setCampaigns(nextCampaigns);
      setClients(clientPayload.clients ?? []);
      setMetaDefaults(metaDefaultsResult.payload);
      setMetaDefaultsError(metaDefaultsResult.error);
      setCampaignDeliveryPresets(deliveryPresetsResult.payload.presets ?? []);
      if (deliveryPresetsResult.error) {
        onError(deliveryPresetsResult.error);
      }
      const currentSelectedId = selectedCampaignIdRef.current;
      const nextSelected = currentSelectedId && nextCampaigns.some((campaign) => campaign.id === currentSelectedId)
        ? currentSelectedId
        : nextCampaigns.find((campaign) => campaign.status !== "archived")?.id ?? nextCampaigns[0]?.id ?? null;
      selectedCampaignIdRef.current = nextSelected;
      setSelectedCampaignId(nextSelected);
      if (nextSelected) {
        setSubmissions((current) => nextSelected === currentSelectedId ? current : []);
        await loadCampaignSubmissions(nextSelected);
      } else {
        campaignSubmissionsRequestId.current += 1;
        setSubmissions([]);
      }
    } catch (reason) {
      if (campaignLoadRequestId.current === requestId) {
        onError(reason instanceof Error ? reason.message : "Could not load campaigns.");
      }
    } finally {
      if (campaignLoadRequestId.current === requestId) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadCampaigns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  async function selectCampaign(campaignId: string) {
    selectedCampaignIdRef.current = campaignId;
    setSelectedCampaignId(campaignId);
    setSubmissions([]);
    setShowDetailDeliveryAdd(false);
    setDetailDeliveryName("");
    setDetailDeliveryPhone("");
    try {
      await loadCampaignSubmissions(campaignId);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not load campaign submissions.");
    }
  }

  function resetCampaignCreateDraft() {
    const metaReady = Boolean(metaDefaults.meta_events_available);
    setCampaignName("");
    setCampaignStatus("draft");
    setDailyBudget("");
    setCampaignLocations([]);
    resetTargetFlow();
    setCreativeBrief("");
    setCreativeHeadline("");
    setCreativeDescription("");
    setCreativeAssetBrief("");
    setCreativeAssets([]);
    setCreativeMediaUrl("");
    setCreativeMediaUploading(false);
    setCreativeMediaDropActive(false);
    setDestinationUrl("");
    setMetaEventsEnabled(metaReady);
    setMetaOptimizeForPixel(metaReady);
    setDeliveryEnabled(true);
    setDeliveryContactIds(["client"]);
    setDeliveryCustomContacts([]);
    setDeliveryCustomName("");
    setDeliveryCustomPhone("");
    setShowCreateDeliveryAdd(false);
    setClientMode("new");
    setExistingClientId("");
    setNewClientName("");
    setNewClientWhatsapp("");
    setNewClientEmail("");
    setNewClientExtraInfo("");
    setFields(defaultCampaignFields());
    setPresentation(defaultCampaignPresentation);
    const resetGraph = campaignMetaPlanGraphFromStrategy({
      strategy: "1x1x3",
      campaignName: "",
      dailyBudget: "",
      locations: [],
      creative: {
        primaryText: "",
        headline: "",
        description: "",
        assetBrief: "",
        destinationUrl: "",
        mediaCount: 0,
        mediaUrl: "",
        callToAction: "LEARN_MORE",
      },
      media: [],
    });
    setMetaPlanStrategy("1x1x3");
    setMetaPlanGraph(resetGraph);
    setSelectedMetaNode(campaignMetaPlanSelection(resetGraph));
  }

  function confirmDiscardCampaignCreateDraft(action: () => void) {
    if (!isCreateView || !campaignCreateDraftDirty) {
      action();
      return;
    }
    setCampaignConfirmDialog({
      id: `campaign-create-discard:${Date.now()}`,
      tone: "warn",
      title: "Discard campaign draft?",
      message: creativeAssets.length
        ? "Discard this create draft? Uploaded creative assets will be detached from this draft, but the already uploaded files may remain stored until backend cleanup."
        : "Discard this create draft? Client, budget, targeting, Delivery, creative, and form edits will be reset.",
      confirmLabel: "Discard draft",
      busyLabel: "Discarding...",
      busyKey: "Discard campaign draft",
      onConfirm: action,
    });
  }

  function openCreateView() {
    const open = () => {
      resetCampaignCreateDraft();
      setCampaignView("create");
    };
    confirmDiscardCampaignCreateDraft(open);
  }

  function closeCreateView() {
    confirmDiscardCampaignCreateDraft(() => {
      resetCampaignCreateDraft();
      setCampaignView("campaigns");
    });
  }

  function rebuildMetaPlanGraph(strategy: MetaPlanStrategy = metaPlanStrategy) {
    const nextGraph = campaignMetaPlanGraphFromStrategy({
      strategy,
      campaignName,
      dailyBudget,
      locations: campaignLocations,
      creative: creativeDraft,
      media: creativeMedia,
    });
    setMetaPlanStrategy(strategy);
    setMetaPlanGraph(nextGraph);
    setSelectedMetaNode(campaignMetaPlanSelection(nextGraph));
  }

  function updateMetaPlanCampaign(campaignId: string, patch: Partial<MetaPlanCampaign>) {
    setMetaPlanGraph((current) => ({
      ...current,
      campaigns: current.campaigns.map((campaign) => campaign.id === campaignId ? { ...campaign, ...patch } : campaign),
    }));
  }

  function updateMetaPlanAdSet(adSetId: string, patch: Partial<MetaPlanAdSet>) {
    setMetaPlanGraph((current) => ({
      ...current,
      campaigns: current.campaigns.map((campaign) => ({
        ...campaign,
        ad_sets: campaign.ad_sets.map((adSet) => adSet.id === adSetId ? { ...adSet, ...patch } : adSet),
      })),
    }));
  }

  function updateMetaPlanAd(adId: string, patch: Partial<MetaPlanAd>) {
    setMetaPlanGraph((current) => ({
      ...current,
      campaigns: current.campaigns.map((campaign) => ({
        ...campaign,
        ad_sets: campaign.ad_sets.map((adSet) => ({
          ...adSet,
          ads: adSet.ads.map((ad) => ad.id === adId ? { ...ad, ...patch } : ad),
        })),
      })),
    }));
  }

  function setSelectedAdMedia(media: MetaPlanCreativeMedia[]) {
    if (selectedMetaNode.type === "ad") {
      updateMetaPlanAd(selectedMetaNode.id, { media });
    }
  }

  function updateMetaEventsEnabled(enabled: boolean) {
    setMetaEventsEnabled(enabled);
    if (!enabled) {
      setMetaOptimizeForPixel(false);
    }
  }

  function updateMetaOptimizeForPixel(enabled: boolean) {
    setMetaOptimizeForPixel(enabled);
    if (enabled) {
      setMetaEventsEnabled(true);
    }
  }

  function buildCreateDeliveryConfig(): CampaignDeliveryConfig {
    const selectedPresets = [
      ...(deliveryContactIds.includes("client") ? [campaignClientDeliveryPreset] : []),
      ...campaignDeliveryPresets.filter((contact) => deliveryContactIds.includes(contact.id)),
    ];
    return campaignDeliveryConfigPayload({
      enabled: deliveryEnabled,
      contacts: [...selectedPresets, ...deliveryCustomContacts],
    });
  }

  function addCreateDeliveryPresetContact(contact: CampaignDeliveryContact) {
    setDeliveryContactIds((current) => current.includes(contact.id) ? current : [...current, contact.id]);
    setShowCreateDeliveryAdd(false);
  }

  function removeCreateDeliveryContact(contact: CampaignDeliveryContact) {
    const current = buildCreateDeliveryConfig();
    if (current.contacts.length <= 1) {
      onError("Delivery needs at least one contact, or turn it off.");
      return;
    }
    if (contact.kind === "custom") {
      setDeliveryCustomContacts((items) => items.filter((item) => item.id !== contact.id));
    } else {
      setDeliveryContactIds((ids) => ids.filter((id) => id !== contact.id));
    }
  }

  function addCreateDeliveryCustomContact() {
    const label = deliveryCustomName.trim();
    const phone = deliveryCustomPhone.trim();
    if (!label || !phone) {
      onError("Delivery contact needs name and phone.");
      return;
    }
    if (buildCreateDeliveryConfig().contacts.some((contact) => contact.phone && contact.phone === phone)) {
      onError("That Delivery contact is already selected.");
      return;
    }
    setDeliveryCustomContacts((current) => [
      ...current,
      { id: `custom-${Date.now()}`, label, phone, kind: "custom" },
    ]);
    setDeliveryCustomName("");
    setDeliveryCustomPhone("");
    setShowCreateDeliveryAdd(false);
  }

  async function updateCampaignDeliveryConfig(campaign: LeadCaptureCampaignItem, nextConfig: CampaignDeliveryConfig): Promise<boolean> {
    setSaving(true);
    try {
      const payload = await apiFetch<{ campaign: LeadCaptureCampaignItem }>(
        `/api/campaigns/${encodeURIComponent(campaign.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ delivery_config: campaignDeliveryConfigPayload(nextConfig) }),
        },
      );
      setCampaigns((current) => current.map((item) => item.id === campaign.id ? payload.campaign : item));
      await loadCampaignSubmissions(campaign.id);
      return true;
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not update campaign delivery.");
      return false;
    } finally {
      setSaving(false);
    }
  }

  function addCampaignDeliveryPresetContact(campaign: LeadCaptureCampaignItem, preset: CampaignDeliveryContact) {
    const current = campaignDeliveryConfigOrDefault(campaign);
    if (campaignDeliveryContactSelected(current, preset.id)) {
      return;
    }
    confirmCampaignDeliveryConfigChange(
      campaign,
      { ...current, contacts: [...current.contacts, preset] },
      `Add ${preset.label} (${campaignDeliveryContactPhoneLabel(preset)}) to live lead routing.`,
      "Add contact",
      () => setShowDetailDeliveryAdd(false),
    );
  }

  function removeCampaignDeliveryContact(campaign: LeadCaptureCampaignItem, contactId: string) {
    const current = campaignDeliveryConfigOrDefault(campaign);
    if (current.contacts.length <= 1) {
      onError("Delivery needs at least one contact, or turn it off.");
      return;
    }
    const contact = current.contacts.find((item) => item.id === contactId);
    const displayContact = campaignDeliveryDisplayContact(contact ?? current.contacts[0], campaign.client);
    confirmCampaignDeliveryConfigChange(
      campaign,
      { ...current, contacts: current.contacts.filter((contact) => contact.id !== contactId) },
      `Remove ${displayContact.label} (${campaignDeliveryContactPhoneLabel(displayContact)}) from lead routing.`,
      "Remove contact",
    );
  }

  function addDetailDeliveryCustomContact(campaign: LeadCaptureCampaignItem) {
    const label = detailDeliveryName.trim();
    const phone = detailDeliveryPhone.trim();
    if (!label || !phone) {
      onError("Delivery contact needs name and phone.");
      return;
    }
    const current = campaignDeliveryConfigOrDefault(campaign);
    if (current.contacts.some((contact) => contact.phone && contact.phone === phone)) {
      onError("That Delivery contact is already selected.");
      return;
    }
    const contact = { id: `custom-${Date.now()}`, label, phone, kind: "custom" } satisfies CampaignDeliveryContact;
    confirmCampaignDeliveryConfigChange(
      campaign,
      { ...current, contacts: [...current.contacts, contact] },
      `Add ${label} (${phone}) to live lead routing.`,
      "Add contact",
      () => {
        setDetailDeliveryName("");
        setDetailDeliveryPhone("");
        setShowDetailDeliveryAdd(false);
      },
    );
  }

  function updateField(index: number, patch: Partial<CampaignFieldDraft>) {
    setFields((current) => current.map((field, fieldIndex) => fieldIndex === index ? { ...field, ...patch } : field));
  }

  function addField() {
    setFields((current) => [
      ...current,
      { id: `field_${current.length + 1}`, label: "Pregunta", type: "text", required: false, placeholder: "", optionsText: "" },
    ]);
  }

  function removeField(index: number) {
    if (fields.length <= 1) {
      onError("Campaign forms need at least one question.");
      return;
    }
    setFields((current) => current.filter((_, fieldIndex) => fieldIndex !== index));
  }

  function resetTargetFlow() {
    setTargetStep("country");
    setCountryQuery("");
    setDraftCountryCode("");
    setProvinceQuery("");
  }

  function selectTargetCountry(countryCode: string) {
    setDraftCountryCode(countryCode);
    setCountryQuery(campaignCountryLabels[countryCode] || countryCode);
    setProvinceQuery("");
    setTargetStep("province");
  }

  function saveTargetLocation(location: CampaignGeoLocation) {
    const validationError = validateCampaignGeoLocations([...campaignLocations, location]);
    if (validationError) {
      onError(validationError);
      return;
    }
    setCampaignLocations((current) => [...current, location]);
    resetTargetFlow();
  }

  function saveWholeCountryTarget() {
    if (!draftCountryCode) {
      return;
    }
    saveTargetLocation({
      country_code: draftCountryCode,
      regions: [],
      cities: [],
    });
  }

  function saveProvinceTarget(area: CampaignGeoArea) {
    if (!draftCountryCode) {
      return;
    }
    const name = area.name.trim();
    if (!name) {
      return;
    }
    saveTargetLocation({
      country_code: draftCountryCode,
      regions: [{ ...area, name, country_code: area.country_code || draftCountryCode }],
      cities: [],
    });
  }

  function removeCampaignLocation(index: number) {
    setCampaignLocations((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  function handleCountrySearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || !countryQuery.trim() || !countryMatches[0]) {
      return;
    }
    event.preventDefault();
    selectTargetCountry(countryMatches[0].value);
  }

  async function saveCampaignDraft(body: Record<string, unknown>) {
    setSaving(true);
    try {
      const payload = await apiFetch<{ campaign: LeadCaptureCampaignItem }>("/api/campaigns", {
        method: "POST",
        body: JSON.stringify(body),
      });
      resetCampaignCreateDraft();
      setCampaignView("campaigns");
      await loadCampaigns();
      await selectCampaign(payload.campaign.id);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not create campaign.");
    } finally {
      setSaving(false);
    }
  }

  async function createCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanName = campaignName.trim();
    if (!cleanName) {
      onError("Campaign name is required.");
      return;
    }
    const usingExistingClient = clientMode === "existing";
    if (usingExistingClient && !existingClientId) {
      onError("Choose an existing client or switch to new client.");
      return;
    }
    const client = usingExistingClient ? null : {
      name: newClientName.trim(),
      whatsapp: newClientWhatsapp.trim(),
      email: newClientEmail.trim() || null,
      extra_info: newClientExtraInfo.trim() || null,
    };
    if (!usingExistingClient && (!client?.name || !client.whatsapp)) {
      onError("Client name and WhatsApp are required.");
      return;
    }
    if (!campaignLocations.length) {
      onError("Elegi al menos un pais.");
      return;
    }
    const nextFormSchema = campaignFormSchema(fields);
    if (campaignStatus === "active" && !nextFormSchema.fields.length) {
      onError("Active forms need at least one question.");
      return;
    }
    const locations = campaignLocations;
    const geoError = validateCampaignGeoLocations(locations);
    if (geoError) {
      onError(geoError);
      return;
    }
    const nextMetaPlanGraph = campaignMetaPlanHydrated(metaPlanGraph, {
      campaignName: cleanName,
      dailyBudget,
      locations,
      creative: creativeDraft,
      media: creativeMedia,
    });
    const body = {
      name: cleanName,
      client_id: usingExistingClient ? existingClientId : null,
      client,
      status: campaignStatus,
      daily_budget_usd: dailyBudget ? Number(dailyBudget) : null,
      geo_targeting: campaignGeoTargeting(locations),
      meta_plan_graph: nextMetaPlanGraph,
      campaign_info: {
        public_presentation: campaignPresentationPayload(presentation),
        creative: {
          primary_text: creativeBrief.trim(),
          headline: creativeHeadline.trim(),
          description: creativeDescription.trim(),
          asset_brief: creativeAssetBrief.trim(),
          media: creativeMedia,
          primary_media_url: creativeAssets[0]?.media_url || creativeMediaUrl.trim(),
          call_to_action: creativeDraft.callToAction,
        },
      },
      creative_brief: creativeSummary || null,
      form_schema: nextFormSchema,
      destination_url: destinationUrl.trim() || null,
      meta_event_name: "Lead",
      meta_events_enabled: metaEventsEnabled || metaOptimizeForPixel,
      meta_optimize_for_pixel: metaOptimizeForPixel,
      meta_optimization: {
        enabled: metaOptimizeForPixel,
        event_name: "Lead",
      },
      delivery_config: buildCreateDeliveryConfig(),
    };
    if (campaignStatus === "active") {
      setCampaignConfirmDialog({
        id: `campaign-create-active-${Date.now()}`,
        tone: "warn",
        title: "Create active campaign?",
        message: `${cleanName} will be active immediately. The public form can start receiving leads and Delivery will route new submissions using the selected contacts.`,
        confirmLabel: "Create active",
        busyLabel: "Creating...",
        busyKey: "Create campaign",
        onConfirm: () => saveCampaignDraft(body),
      });
      return;
    }
    await saveCampaignDraft(body);
  }

  async function patchCampaignStatus(campaign: LeadCaptureCampaignItem, status: string) {
    setSaving(true);
    try {
      const payload = await apiFetch<{ campaign: LeadCaptureCampaignItem }>(
        `/api/campaigns/${encodeURIComponent(campaign.id)}`,
        { method: "PATCH", body: JSON.stringify({ status }) },
      );
      setCampaigns((current) => current.map((item) => item.id === campaign.id ? payload.campaign : item));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not update campaign.");
    } finally {
      setSaving(false);
    }
  }

  function confirmCampaignStatusChange(campaign: LeadCaptureCampaignItem, status: string) {
    const confirmText = campaignStatusConfirmText(campaign.name, campaign.status, status);
    setCampaignConfirmDialog({
      id: `campaign-status-${campaign.id}-${status}`,
      tone: "warn",
      title: confirmText.title,
      message: confirmText.message,
      confirmLabel: confirmText.confirmLabel,
      busyLabel: "Saving...",
      busyKey: "Campaign status",
      onConfirm: () => patchCampaignStatus(campaign, status),
    });
  }

  function confirmCampaignDeliveryConfigChange(
    campaign: LeadCaptureCampaignItem,
    nextConfig: CampaignDeliveryConfig,
    message: string,
    confirmLabel: string,
    afterConfirm?: () => void,
  ) {
    setCampaignConfirmDialog({
      id: `campaign-delivery-${campaign.id}-${Date.now()}`,
      tone: "warn",
      title: "Update campaign Delivery?",
      message: `${campaign.name}: ${message}`,
      confirmLabel,
      busyLabel: "Saving...",
      busyKey: "Campaign Delivery",
      onConfirm: async () => {
        if (await updateCampaignDeliveryConfig(campaign, nextConfig)) {
          afterConfirm?.();
        }
      },
    });
  }

  function closeCampaignConfirmDialog() {
    if (saving) {
      return;
    }
    setCampaignConfirmDialog(null);
  }

  async function submitCampaignConfirmDialog(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const currentDialog = campaignConfirmDialog;
    if (!currentDialog || saving) {
      return;
    }
    await currentDialog.onConfirm();
    setCampaignConfirmDialog((activeDialog) => activeDialog?.id === currentDialog.id ? null : activeDialog);
  }

  function deleteCampaign(campaign: LeadCaptureCampaignItem) {
    setCampaignConfirmDialog({
      id: `delete-campaign-${campaign.id}`,
      tone: "danger",
      title: "Delete campaign?",
      message: `Delete ${campaign.name} permanently? If it has live Meta ads, the CRM will pause them first.`,
      confirmLabel: "Delete",
      busyLabel: "Deleting...",
      busyKey: "Deleting campaign",
      onConfirm: async () => {
        setSaving(true);
        try {
          await apiFetch(`/api/campaigns/${encodeURIComponent(campaign.id)}`, { method: "DELETE" });
          setCampaigns((current) => current.filter((item) => item.id !== campaign.id));
          if (selectedCampaignId === campaign.id) {
            setSelectedCampaignId(null);
          }
          await loadCampaigns();
        } catch (reason) {
          onError(reason instanceof Error ? reason.message : "Could not delete campaign.");
        } finally {
          setSaving(false);
        }
      },
    });
  }

  async function refreshDeliverySource(campaign: LeadCaptureCampaignItem) {
    setSaving(true);
    try {
      await apiFetch(`/api/campaigns/${encodeURIComponent(campaign.id)}/delivery-source`, { method: "POST" });
      await loadCampaigns();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not refresh campaign delivery.");
    } finally {
      setSaving(false);
    }
  }

  function requestRefreshDeliverySource(campaign: LeadCaptureCampaignItem) {
    if (campaign.status !== "active" && campaign.status !== "published") {
      void refreshDeliverySource(campaign);
      return;
    }
    setCampaignConfirmDialog({
      id: `campaign-delivery-source-${campaign.id}`,
      tone: "warn",
      title: "Refresh Delivery source?",
      message: `${campaign.name} is ${humanize(campaign.status)}. Refreshing the Delivery source can update enabled recipient routing for future public submissions.`,
      confirmLabel: "Refresh source",
      busyLabel: "Refreshing...",
      busyKey: "Campaign Delivery source",
      onConfirm: () => refreshDeliverySource(campaign),
    });
  }

  async function copyCampaignUrl(campaign: LeadCaptureCampaignItem) {
    await navigator.clipboard.writeText(campaign.public_url);
  }

  function renderMetaPlanEditor() {
    if (selectedMetaNode.type === "campaign" && selectedGraphCampaign) {
      return (
        <div className="campaign-meta-plan-editor">
          <div className="campaign-meta-plan-editor-head">
            <span>Campaign</span>
            <strong>{selectedGraphCampaign.name}</strong>
          </div>
          <div className="campaign-meta-plan-fields">
            <label className="ct-field">
              <span>Name</span>
              <input value={selectedGraphCampaign.name} onChange={(event) => updateMetaPlanCampaign(selectedGraphCampaign.id, { name: event.target.value })} />
            </label>
            <label className="ct-field">
              <span>Budget diario USD</span>
              <input
                value={selectedGraphCampaign.budget_daily_usd ?? ""}
                onChange={(event) => updateMetaPlanCampaign(selectedGraphCampaign.id, { budget_daily_usd: event.target.value ? Number(event.target.value) : null })}
                inputMode="numeric"
                placeholder={dailyBudget || "25"}
              />
            </label>
            <label className="ct-field">
              <span>Objective</span>
              <select value={selectedGraphCampaign.objective} onChange={(event) => updateMetaPlanCampaign(selectedGraphCampaign.id, { objective: event.target.value })}>
                <option value="OUTCOME_LEADS">Leads</option>
                <option value="OUTCOME_TRAFFIC">Traffic</option>
                <option value="OUTCOME_SALES">Sales</option>
              </select>
            </label>
          </div>
        </div>
      );
    }

    if (selectedMetaNode.type === "ad_set" && selectedGraphAdSet) {
      return (
        <div className="campaign-meta-plan-editor">
          <div className="campaign-meta-plan-editor-head">
            <span>Ad set</span>
            <strong>{selectedGraphAdSet.name}</strong>
          </div>
          <div className="campaign-meta-plan-fields">
            <label className="ct-field">
              <span>Name</span>
              <input value={selectedGraphAdSet.name} onChange={(event) => updateMetaPlanAdSet(selectedGraphAdSet.id, { name: event.target.value })} />
            </label>
            <div className="campaign-control-block campaign-meta-plan-wide">
              <span>Destination</span>
              <div className="campaign-segmented" role="group" aria-label="Ad set destination">
                {[
                  { value: "form", label: "Form" },
                  { value: "website", label: "Website" },
                  { value: "whatsapp", label: "WhatsApp" },
                ].map((item) => (
                  <button
                    type="button"
                    key={item.value}
                    className={selectedGraphAdSet.destination_type === item.value ? "is-active" : ""}
                    aria-pressed={selectedGraphAdSet.destination_type === item.value}
                    onClick={() => updateMetaPlanAdSet(selectedGraphAdSet.id, { destination_type: item.value as MetaPlanAdSet["destination_type"] })}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
            <label className="ct-field">
              <span>Performance goal</span>
              <select value={selectedGraphAdSet.optimization_goal} onChange={(event) => updateMetaPlanAdSet(selectedGraphAdSet.id, { optimization_goal: event.target.value, performance_goal: event.target.value })}>
                <option value="LEAD_GENERATION">Lead generation</option>
                <option value="OFFSITE_CONVERSIONS">Pixel Lead</option>
                <option value="LINK_CLICKS">Link clicks</option>
              </select>
            </label>
            <label className="ct-field">
              <span>Facebook Page ID</span>
              <input value={selectedGraphAdSet.page_id || ""} onChange={(event) => updateMetaPlanAdSet(selectedGraphAdSet.id, { page_id: event.target.value })} placeholder="Optional until publish" />
            </label>
            <label className="ct-field">
              <span>Instagram Actor ID</span>
              <input value={selectedGraphAdSet.instagram_actor_id || ""} onChange={(event) => updateMetaPlanAdSet(selectedGraphAdSet.id, { instagram_actor_id: event.target.value })} placeholder="Optional" />
            </label>
            {selectedGraphAdSet.destination_type === "website" ? (
              <label className="ct-field campaign-meta-plan-wide">
                <span>Website URL</span>
                <input value={selectedGraphAdSet.landing_page_url || ""} onChange={(event) => updateMetaPlanAdSet(selectedGraphAdSet.id, { landing_page_url: event.target.value })} placeholder="https://..." />
              </label>
            ) : null}
            {selectedGraphAdSet.destination_type === "whatsapp" ? (
              <label className="ct-field campaign-meta-plan-wide">
                <span>WhatsApp Phone Number ID</span>
                <input value={selectedGraphAdSet.whatsapp_phone_number_id || ""} onChange={(event) => updateMetaPlanAdSet(selectedGraphAdSet.id, { whatsapp_phone_number_id: event.target.value })} placeholder="Meta phone number id" />
              </label>
            ) : null}
          </div>
        </div>
      );
    }

    if (selectedMetaNode.type === "ad" && selectedGraphAd) {
      return (
        <div className="campaign-meta-plan-editor">
          <div className="campaign-meta-plan-editor-head">
            <span>Ad</span>
            <strong>{selectedGraphAd.name}</strong>
          </div>
          <div className="campaign-meta-plan-fields">
            <label className="ct-field">
              <span>Name</span>
              <input value={selectedGraphAd.name} onChange={(event) => updateMetaPlanAd(selectedGraphAd.id, { name: event.target.value })} />
            </label>
            <label className="ct-field">
              <span>CTA</span>
              <select value={selectedGraphAd.call_to_action} onChange={(event) => updateMetaPlanAd(selectedGraphAd.id, { call_to_action: event.target.value })}>
                <option value="LEARN_MORE">Learn more</option>
                <option value="SIGN_UP">Sign up</option>
                <option value="CONTACT_US">Contact us</option>
                <option value="WHATSAPP_MESSAGE">WhatsApp</option>
              </select>
            </label>
            <label className="ct-field campaign-meta-plan-wide">
              <span>Primary text</span>
              <textarea value={selectedGraphAd.primary_text} onChange={(event) => updateMetaPlanAd(selectedGraphAd.id, { primary_text: event.target.value })} rows={3} placeholder="Main ad text" />
            </label>
            <label className="ct-field">
              <span>Headline</span>
              <input value={selectedGraphAd.headline} onChange={(event) => updateMetaPlanAd(selectedGraphAd.id, { headline: event.target.value })} placeholder="Short title" />
            </label>
            <label className="ct-field">
              <span>Description</span>
              <input value={selectedGraphAd.description} onChange={(event) => updateMetaPlanAd(selectedGraphAd.id, { description: event.target.value })} placeholder="Optional line" />
            </label>
            <label className="ct-field campaign-meta-plan-wide">
              <span>Redirect URL</span>
              <input value={selectedGraphAd.destination_url} onChange={(event) => updateMetaPlanAd(selectedGraphAd.id, { destination_url: event.target.value })} placeholder="https://..." />
            </label>
            <div className="campaign-meta-plan-media campaign-meta-plan-wide">
              <div>
                <span>Media</span>
                <strong>{compactNumber(selectedGraphAd.media.length)} attached</strong>
              </div>
              <button type="button" className="ct-btn ct-btn-ghost" onClick={() => setSelectedAdMedia(creativeMedia)} disabled={!creativeMedia.length}>
                <UploadSimple size={13} weight="bold" />
                Use uploaded media
              </button>
            </div>
          </div>
        </div>
      );
    }

    return <CtEmptyState compact title="Select a node" message="Choose a campaign, ad set, or ad." />;
  }

  function renderCampaignCard(campaign: LeadCaptureCampaignItem) {
    const archived = campaign.status === "archived";
    return (
      <button
        type="button"
        className={`campaign-card ${archived ? "is-archived" : ""} ${selectedCampaign?.id === campaign.id ? "active" : ""}`}
        key={campaign.id}
        onClick={() => void selectCampaign(campaign.id)}
      >
        <div>
          <strong>{campaign.name}</strong>
          <span>{campaign.client?.display_name || "No client"} · {campaign.location || "No location"}</span>
        </div>
        <span className="delivery-status-pill" data-tone={campaign.status === "active" ? "success" : campaign.status === "paused" ? "warn" : "muted"}>
          {humanize(campaign.status)}
        </span>
        <small>{compactNumber(campaign.submission_count)} leads</small>
      </button>
    );
  }

  return (
    <section className={`ct-surface campaign-manager-surface ${showCampaignEmpty && !isCreateView ? "is-empty" : ""}`}>
      <div className="ct-simple-head campaign-manager-head">
        <div className="ct-simple-title">
          <span>Ads</span>
          <strong>{isCreateView ? "Create campaign" : campaigns.length ? `${compactNumber(campaigns.length)} forms` : "No forms yet"}</strong>
          <small>{isCreateView ? "New owned lead form" : selectedCampaign ? selectedCampaign.name : "Owned lead capture"}</small>
        </div>
        <div className="campaign-view-switch" role="tablist" aria-label="Ads views">
          <button
            type="button"
            role="tab"
            aria-selected={!isCreateView}
            className={!isCreateView ? "active" : ""}
            onClick={closeCreateView}
          >
            <ListChecks size={14} weight="bold" />
            Mis campañas
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={isCreateView}
            className={isCreateView ? "active" : ""}
            onClick={openCreateView}
          >
            <Plus size={14} weight="bold" />
            Crear campaña
          </button>
        </div>
        <div className="ct-simple-metrics campaign-manager-metrics">
          <span><strong>{compactNumber(campaigns.reduce((total, campaign) => total + (campaign.submission_count || 0), 0))}</strong>Leads</span>
          <span><strong>{compactNumber(activeCampaignCount)}</strong>Active</span>
          <span><strong>{compactNumber(clients.length)}</strong>Clients</span>
        </div>
        <div className="campaign-manager-actions">
          {isCreateView ? (
            <button type="button" className="ct-btn ct-btn-ghost" onClick={closeCreateView}>
              Mis campañas
            </button>
          ) : (
            <>
              <button type="button" className="ct-btn ct-btn-ghost" onClick={() => void loadCampaigns()} disabled={loading}>
                <ArrowsClockwise size={14} weight="bold" />
                Refresh
              </button>
              <button type="button" className="ct-btn ct-btn-primary" onClick={openCreateView}>
                <Plus size={14} weight="bold" />
                New campaign
              </button>
            </>
          )}
        </div>
      </div>

      {metaDefaultsError ? (
        <div className="campaign-meta-warning" role="alert">
          <WarningCircle size={16} weight="bold" />
          <span>Meta defaults did not load: {metaDefaultsError}</span>
        </div>
      ) : null}

      {isCreateView ? (
        <form id="campaign-create-form" className="campaign-create-panel campaign-create-studio" onSubmit={createCampaign}>
          <div className="campaign-create-sticky-actions">
            <button type="button" className="ct-btn ct-btn-ghost" onClick={closeCreateView}>Cancel</button>
            <button type="submit" className="ct-btn campaign-create-primary" disabled={saving}>
              <Check size={14} weight="bold" />
              {saving ? "Saving..." : "Create campaign"}
            </button>
          </div>
          <div className="campaign-create-main">
            <section className="campaign-create-section campaign-section-plan">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><Megaphone size={16} weight="bold" /></span>
                <div>
                  <strong>1. Meta plan</strong>
                  <small>{metaPlanCounts.campaigns} campaigns · {metaPlanCounts.adSets} ad sets · {metaPlanCounts.ads} ads</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-meta-plan">
                <div className="campaign-meta-plan-toolbar">
                  <div className="campaign-segmented" role="group" aria-label="Meta plan strategy">
                    {metaPlanStrategies.map((strategy) => (
                      <button
                        type="button"
                        key={strategy.value}
                        className={metaPlanStrategy === strategy.value ? "is-active" : ""}
                        aria-pressed={metaPlanStrategy === strategy.value}
                        onClick={() => rebuildMetaPlanGraph(strategy.value)}
                      >
                        {strategy.label}
                      </button>
                    ))}
                  </div>
                  <button type="button" className="ct-btn ct-btn-ghost" onClick={() => rebuildMetaPlanGraph(metaPlanStrategy)}>
                    Rebuild
                  </button>
                </div>
                <div className="campaign-meta-plan-grid">
                  <div className="campaign-meta-plan-tree" aria-label="Meta plan tree">
                    {metaPlanGraph.campaigns.map((campaign) => (
                      <div className="campaign-meta-plan-campaign" key={campaign.id}>
                        <button
                          type="button"
                          className={selectedMetaNode.type === "campaign" && selectedMetaNode.id === campaign.id ? "active" : ""}
                          onClick={() => setSelectedMetaNode({ type: "campaign", id: campaign.id })}
                        >
                          <span>Campaign</span>
                          <strong>{campaign.name}</strong>
                        </button>
                        {campaign.ad_sets.map((adSet) => (
                          <div className="campaign-meta-plan-adset" key={adSet.id}>
                            <button
                              type="button"
                              className={selectedMetaNode.type === "ad_set" && selectedMetaNode.id === adSet.id ? "active" : ""}
                              onClick={() => setSelectedMetaNode({ type: "ad_set", id: adSet.id })}
                            >
                              <span>Ad set · {humanize(adSet.destination_type)}</span>
                              <strong>{adSet.name}</strong>
                            </button>
                            {adSet.ads.map((ad) => (
                              <button
                                type="button"
                                className={`campaign-meta-plan-ad ${selectedMetaNode.type === "ad" && selectedMetaNode.id === ad.id ? "active" : ""}`}
                                key={ad.id}
                                onClick={() => setSelectedMetaNode({ type: "ad", id: ad.id })}
                              >
                                <span>Ad</span>
                                <strong>{ad.name}</strong>
                              </button>
                            ))}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                  {renderMetaPlanEditor()}
                </div>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-basics">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><NotePencil size={16} weight="bold" /></span>
                <div>
                  <strong>2. Basics</strong>
                  <small>Name, status and budget</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-basics-grid">
                <label className="ct-field">
                  <span>Campaign name</span>
                  <input value={campaignName} onChange={(event) => setCampaignName(event.target.value)} required placeholder="Campaña Facu Contadores" />
                </label>
                <div className="campaign-control-block">
                  <span>Status</span>
                  <div className="campaign-segmented" role="group" aria-label="Campaign status">
                    {["draft", "active", "paused"].map((status) => (
                      <button
                        type="button"
                        className={campaignStatus === status ? "is-active" : ""}
                        key={status}
                        aria-pressed={campaignStatus === status}
                        onClick={() => setCampaignStatus(status)}
                      >
                        {humanize(status)}
                      </button>
                    ))}
                  </div>
                </div>
                <label className="ct-field">
                  <span>Daily budget (USD)</span>
                  <input value={dailyBudget} onChange={(event) => setDailyBudget(event.target.value)} inputMode="numeric" placeholder="25" />
                </label>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-targeting">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><Megaphone size={16} weight="bold" /></span>
                <div>
                  <strong>3. Ubicacion</strong>
                  <small>Pais o provincia</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-targeting-panel">
                <div className="campaign-targeting-saved" aria-label="Ubicaciones elegidas">
                  {campaignLocations.map((location, index) => (
                    <button
                      type="button"
                      className="campaign-target-pill"
                      key={`${location.country_code}-${campaignLocationDetailLabel(location)}-${index}`}
                      onClick={() => removeCampaignLocation(index)}
                      aria-label={`Quitar ${campaignGeoLocationLabel(location)}`}
                    >
                      <span>{campaignLocationKindLabel(location)}</span>
                      <strong>{campaignLocationButtonLabel(location)}</strong>
                      <X size={13} weight="bold" />
                    </button>
                  ))}
                </div>

                <div className="campaign-target-flow">
                  {targetStep === "country" ? (
                    <>
                      <label className="campaign-target-question" htmlFor="campaign-country-search">
                        Pais
                      </label>
                      <div className="campaign-command-input">
                        <input
                          id="campaign-country-search"
                          value={countryQuery}
                          onChange={(event) => setCountryQuery(event.target.value)}
                          onKeyDown={handleCountrySearchKeyDown}
                          placeholder="Buscar pais"
                        />
                      </div>
                      {countryQuery.trim() && countryMatches.length ? (
                        <div className="campaign-country-results">
                          {countryMatches.map((country) => (
                            <button type="button" key={country.value} onClick={() => selectTargetCountry(country.value)}>
                              <span>{country.label}</span>
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <>
                      <div className="campaign-target-question is-row">
                        <strong>{draftCountryLabel}</strong>
                        <button type="button" className="ct-icon-btn" onClick={resetTargetFlow} aria-label="Cambiar pais">
                          <X size={13} weight="bold" />
                        </button>
                      </div>
                      <button type="button" className="campaign-target-choice" onClick={saveWholeCountryTarget}>
                        <span>Pais entero</span>
                        <Check size={14} weight="bold" />
                      </button>
                      <label className="campaign-target-question" htmlFor="campaign-province-search">
                        Provincia
                      </label>
                      <CampaignProvinceSearch
                        countryCode={draftCountryCode}
                        query={provinceQuery}
                        onQueryChange={setProvinceQuery}
                        onPick={saveProvinceTarget}
                        onError={onError}
                      />
                    </>
                  )}
                </div>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-client">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><ChatCircleText size={16} weight="bold" /></span>
                <div>
                  <strong>4. Client</strong>
                  <small>Existing or new</small>
                </div>
              </div>
              <div className="campaign-section-body">
                <div className="campaign-client-mode">
                  <div className="campaign-segmented" role="group" aria-label="Client source">
                    <button
                      type="button"
                      className={clientMode === "existing" ? "is-active" : ""}
                      disabled={!clients.length}
                      aria-pressed={clientMode === "existing"}
                      onClick={() => {
                        setClientMode("existing");
                        setExistingClientId((current) => current || clients[0]?.id || "");
                      }}
                    >
                      Existing client
                    </button>
                    <button
                      type="button"
                      className={clientMode === "new" ? "is-active" : ""}
                      aria-pressed={clientMode === "new"}
                      onClick={() => {
                        setClientMode("new");
                        setExistingClientId("");
                      }}
                    >
                      New client
                    </button>
                  </div>
                  {clientMode === "existing" ? (
                    <label className="ct-field">
                      <span>Choose client</span>
                      <select value={existingClientId} onChange={(event) => setExistingClientId(event.target.value)}>
                        <option value="" disabled>Select one client</option>
                        {clients.map((client) => (
                          <option key={client.id} value={client.id}>{campaignClientLabel(client)}</option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                </div>
                {clientMode === "new" ? (
                  <>
                    <div className="campaign-client-fields">
                      <label className="ct-field">
                        <span>Client name</span>
                        <input value={newClientName} onChange={(event) => setNewClientName(event.target.value)} placeholder="New converted client" />
                      </label>
                      <label className="ct-field">
                        <span>WhatsApp</span>
                        <input value={newClientWhatsapp} onChange={(event) => setNewClientWhatsapp(event.target.value)} inputMode="tel" placeholder="549..." />
                      </label>
                      <label className="ct-field">
                        <span>Email</span>
                        <input value={newClientEmail} onChange={(event) => setNewClientEmail(event.target.value)} type="text" inputMode="email" autoComplete="email" placeholder="cliente@email.com" />
                      </label>
                    </div>
                    <label className="ct-field">
                      <span>Extra info</span>
                      <textarea value={newClientExtraInfo} onChange={(event) => setNewClientExtraInfo(event.target.value)} rows={2} placeholder="Notes for this client" />
                    </label>
                  </>
                ) : (
                  <div className="campaign-existing-client-summary">
                    <strong>{selectedClient?.display_name || "No client selected"}</strong>
                    <span>{selectedClient?.lead?.phone || "Choose a saved converted client"}{selectedClient?.lead?.email ? ` · ${selectedClient.lead.email}` : ""}</span>
                  </div>
                )}
              </div>
            </section>

            <section className="campaign-create-section campaign-section-delivery">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><PaperPlaneTilt size={16} weight="bold" /></span>
                <div>
                  <strong>5. Delivery</strong>
                  <small>WhatsApp templates</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-delivery-config">
                <label className="campaign-delivery-toggle">
                  <span>
                    <strong>Auto delivery</strong>
                    <small>{deliveryEnabled ? "On" : "Off"}</small>
                  </span>
                  <input type="checkbox" checked={deliveryEnabled} onChange={(event) => setDeliveryEnabled(event.target.checked)} />
                </label>
                <div className="campaign-delivery-current">
                  <div className="campaign-delivery-current-head">
                    <strong>Delivery contacts</strong>
                    <button type="button" className="ct-btn ct-btn-ghost" onClick={() => setShowCreateDeliveryAdd((open) => !open)}>
                      <Plus size={13} weight="bold" />
                      Contact
                    </button>
                  </div>
                  <div className="campaign-delivery-contact-list">
                    {createDeliveryConfig.contacts.map((contact) => {
                      const displayContact = campaignDeliveryDisplayContact(contact, createDeliveryClient);
                      return (
                        <article className="campaign-delivery-contact-card" key={contact.id}>
                          <div>
                            <strong>{displayContact.label}</strong>
                            <span>{campaignDeliveryContactPhoneLabel(displayContact)}</span>
                          </div>
                          <button type="button" className="ct-icon-btn" onClick={() => removeCreateDeliveryContact(contact)} aria-label={`Remove ${displayContact.label}`}>
                            <X size={12} weight="bold" />
                          </button>
                        </article>
                      );
                    })}
                  </div>
                </div>
                {showCreateDeliveryAdd ? (
                  <div className="campaign-delivery-add-panel">
                    {createDeliverySuggestions.length ? (
                      <div className="campaign-delivery-suggestion-grid">
                        {createDeliverySuggestions.map((contact) => (
                          <button type="button" key={contact.id} onClick={() => addCreateDeliveryPresetContact(contact)}>
                            <span>{contact.label}</span>
                            <small>{campaignDeliveryContactPhoneLabel(contact)}</small>
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <div className="campaign-delivery-custom">
                      <label className="ct-field">
                        <span>Name</span>
                        <input value={deliveryCustomName} onChange={(event) => setDeliveryCustomName(event.target.value)} placeholder="Delivery contact" />
                      </label>
                      <label className="ct-field">
                        <span>Phone</span>
                        <input value={deliveryCustomPhone} onChange={(event) => setDeliveryCustomPhone(event.target.value)} inputMode="tel" placeholder="549..." />
                      </label>
                      <button type="button" className="ct-btn ct-btn-ghost" onClick={addCreateDeliveryCustomContact}>
                        <Plus size={13} weight="bold" />
                        Add
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </section>

            <section className="campaign-create-section campaign-section-creative">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><Camera size={16} weight="bold" /></span>
                <div>
                  <strong>6. Creative</strong>
                  <small>Media and copy</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-creative-grid">
                <div
                  className={`campaign-creative-upload ${creativeMediaDropActive ? "drag-active" : ""}`}
                  onDragOver={handleCampaignCreativeDragOver}
                  onDragLeave={handleCampaignCreativeDragLeave}
                  onDrop={handleCampaignCreativeDrop}
                  onPaste={handleCampaignCreativePaste}
                  tabIndex={0}
                >
                  <div>
                    <strong>Upload image or video</strong>
                    <span>Files upload immediately as draft assets. Remove detaches them from this campaign draft.</span>
                  </div>
                  <label className="ct-btn ct-btn-primary campaign-creative-upload-button">
                    <UploadSimple size={15} weight="bold" />
                    {creativeMediaUploading ? "Uploading..." : "Upload media"}
                    <input
                      type="file"
                      accept="image/*,video/*"
                      multiple
                      disabled={creativeMediaUploading}
                      onChange={(event) => {
                        const files = Array.from(event.target.files ?? []);
                        event.currentTarget.value = "";
                        void uploadCampaignCreativeFiles(files);
                      }}
                    />
                  </label>
                </div>
                {creativeAssets.length ? (
                  <div className="campaign-creative-assets">
                    {creativeAssets.map((asset) => (
                      <article className="campaign-creative-asset" key={asset.id}>
                        <div className="campaign-creative-asset-preview">
                          {asset.asset_type === "image" && asset.media_url ? (
                            <img src={asset.media_url} alt={campaignCreativeAssetName(asset)} loading="lazy" />
                          ) : asset.asset_type === "video" && asset.media_url ? (
                            <video src={asset.media_url} controls preload="metadata" />
                          ) : (
                            <FolderOpen size={22} weight="bold" />
                          )}
                        </div>
                        <div>
                          <strong>{campaignCreativeAssetName(asset)}</strong>
                          <span>{humanize(asset.asset_type)} draft upload · removable from draft</span>
                        </div>
                        <button
                          type="button"
                          className="ct-icon-btn"
                          onClick={() => removeCampaignCreativeAsset(asset.id)}
                          aria-label="Remove draft creative media from this campaign"
                          title="Detach from this draft"
                        >
                          <X size={13} weight="bold" />
                        </button>
                      </article>
                    ))}
                  </div>
                ) : null}
                <label className="ct-field campaign-creative-primary">
                  <span>Media URL (optional)</span>
                  <input
                    value={creativeMediaUrl}
                    onChange={(event) => {
                      const nextUrl = event.target.value;
                      setCreativeMediaUrl(nextUrl);
                      if (selectedMetaNode.type === "ad") {
                        setSelectedAdMedia(campaignMetaPlanMedia(creativeAssets, nextUrl));
                      }
                    }}
                    placeholder="https://.../ad-image.png"
                  />
                </label>
                <label className="ct-field campaign-creative-primary">
                  <span>Primary text</span>
                  <textarea value={creativeBrief} onChange={(event) => setCreativeBrief(event.target.value)} rows={3} placeholder="Main ad text shown above the image/video" />
                </label>
                <label className="ct-field">
                  <span>Headline</span>
                  <input value={creativeHeadline} onChange={(event) => setCreativeHeadline(event.target.value)} placeholder="Short offer headline" />
                </label>
                <label className="ct-field">
                  <span>Description</span>
                  <input value={creativeDescription} onChange={(event) => setCreativeDescription(event.target.value)} placeholder="Optional supporting line" />
                </label>
                <label className="ct-field campaign-creative-primary">
                  <span>Asset notes</span>
                  <textarea value={creativeAssetBrief} onChange={(event) => setCreativeAssetBrief(event.target.value)} rows={2} placeholder="Contador en oficina, testimonial corto, placa de beneficios..." />
                </label>
                <label className="ct-field campaign-creative-primary">
                  <span>Destination URL</span>
                  <input value={destinationUrl} onChange={(event) => setDestinationUrl(event.target.value)} placeholder="https://..." />
                </label>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-form">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><NotePencil size={16} weight="bold" /></span>
                <div>
                  <strong>7. Public copy</strong>
                  <small>Lead-facing form text</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-form-builder">
                <div className="campaign-field-editor">
                  <label className="ct-field">
                    <span>Eyebrow</span>
                    <input value={presentation.eyebrow} maxLength={40} onChange={(event) => setPresentation((current) => ({ ...current, eyebrow: event.target.value }))} />
                  </label>
                  <label className="ct-field campaign-field-label">
                    <span>Title</span>
                    <input value={presentation.title} maxLength={80} onChange={(event) => setPresentation((current) => ({ ...current, title: event.target.value }))} />
                  </label>
                  <label className="ct-field">
                    <span>Submit label</span>
                    <input value={presentation.submitLabel} maxLength={40} onChange={(event) => setPresentation((current) => ({ ...current, submitLabel: event.target.value }))} />
                  </label>
                  <label className="ct-field">
                    <span>Theme</span>
                    <select value={presentation.theme} onChange={(event) => setPresentation((current) => ({ ...current, theme: event.target.value as CampaignPresentationTheme }))}>
                      <option value="default">Default</option>
                      <option value="light">Light</option>
                      <option value="contrast">Contrast</option>
                    </select>
                  </label>
                </div>
                <label className="ct-field">
                  <span>Trust cue</span>
                  <input value={presentation.trustCue} maxLength={120} onChange={(event) => setPresentation((current) => ({ ...current, trustCue: event.target.value }))} placeholder="Optional short reassurance shown near the form" />
                </label>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-form">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><ListChecks size={16} weight="bold" /></span>
                <div>
                  <strong>8. Form fields</strong>
                  <small>{fields.length} fields</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-form-builder">
                <div className="campaign-form-builder-head">
                  <div>
                    <span>Lead form</span>
                    <strong>Questions people complete</strong>
                  </div>
                  <button type="button" className="ct-btn ct-btn-ghost" onClick={addField}>
                    <Plus size={13} weight="bold" />
                    Field
                  </button>
                </div>
                <div className="campaign-field-list">
                  {fields.map((field, index) => {
                    const typeLabel = campaignFieldTypes.find((type) => type.value === field.type)?.label || field.type;
                    return (
                      <article className="campaign-field-card" key={`${field.id}-${index}`}>
                        <div className="campaign-field-card-head">
                          <div>
                            <span>Field {index + 1}</span>
                            <strong>{field.label.trim() || "Untitled field"}</strong>
                          </div>
                          <div className="campaign-field-badges">
                            <span>{typeLabel}</span>
                            <span className={field.required ? "is-required" : "is-optional"}>{field.required ? "Required" : "Optional"}</span>
                          </div>
                          <button type="button" className="ct-icon-btn" onClick={() => removeField(index)} aria-label="Remove field">
                            <Trash size={14} weight="bold" />
                          </button>
                        </div>
                        <div className="campaign-field-editor">
                          <label className="ct-field campaign-field-label">
                            <span>Label</span>
                            <input value={field.label} onChange={(event) => updateField(index, { label: event.target.value, id: campaignFieldId(event.target.value, index) })} />
                          </label>
                          <label className="ct-field">
                            <span>Type</span>
                            <select value={field.type} onChange={(event) => updateField(index, { type: event.target.value })}>
                              {campaignFieldTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                            </select>
                          </label>
                          <label className="ct-field">
                            <span>Placeholder</span>
                            <input value={field.placeholder || ""} onChange={(event) => updateField(index, { placeholder: event.target.value })} placeholder="Shown inside the form field" />
                          </label>
                          <label className="campaign-required-toggle">
                            <input type="checkbox" checked={Boolean(field.required)} onChange={(event) => updateField(index, { required: event.target.checked })} />
                            <span>{field.required ? "Required" : "Optional"}</span>
                          </label>
                        </div>
                        {(field.type === "select" || field.type === "multi_select") ? (
                          <label className="ct-field campaign-field-options">
                            <span>Options</span>
                            <input value={field.optionsText} onChange={(event) => updateField(index, { optionsText: event.target.value })} placeholder="Opcion 1, Opcion 2" />
                          </label>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-meta">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><Pulse size={16} weight="bold" /></span>
                <div>
                  <strong>9. Meta</strong>
                  <small>Submit tracking</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-meta-grid">
                <label className="campaign-meta-card">
                  <span className="campaign-meta-card-main">
                    <span>
                      <strong>Meta Pixel</strong>
                      <small>{metaEventsEnabled ? "Lead event on submit" : "Disabled for this campaign"}</small>
                    </span>
                    <span className="ct-field-toggle campaign-meta-switch">
                      <input
                        type="checkbox"
                        checked={metaEventsEnabled}
                        onChange={(event) => updateMetaEventsEnabled(event.target.checked)}
                      />
                    </span>
                  </span>
                  <em>{metaDefaults.meta_events_available ? metaDefaults.pixel_label || "Automatic pixel ready" : "No synced pixel yet"}</em>
                </label>
                <label className="campaign-meta-card">
                  <span className="campaign-meta-card-main">
                    <span>
                      <strong>Optimize Ad Set</strong>
                      <small>{metaOptimizeForPixel ? "Meta optimizes for Lead" : "Manual optimization later"}</small>
                    </span>
                    <span className="ct-field-toggle campaign-meta-switch">
                      <input
                        type="checkbox"
                        checked={metaOptimizeForPixel}
                        disabled={!metaDefaults.meta_events_available}
                        onChange={(event) => updateMetaOptimizeForPixel(event.target.checked)}
                      />
                    </span>
                  </span>
                  <em>{metaOptimizeForPixel ? "OFFSITE_CONVERSIONS · Lead" : "No pixel optimization"}</em>
                </label>
                <div className="campaign-meta-event-card">
                  <span>Event</span>
                  <strong>Lead</strong>
                  <small>Pixel browser + server CAPI</small>
                </div>
              </div>
            </section>
          </div>

          <aside className="campaign-create-preview">
            <section className="campaign-form-preview" aria-label="Campaign form preview">
              <div className="campaign-preview-head">
                <span>{campaignPresentationPayload(presentation).eyebrow}</span>
                <strong>{campaignPresentationPayload(presentation).title}</strong>
                {campaignPresentationPayload(presentation).trust_cue ? <small>{campaignPresentationPayload(presentation).trust_cue}</small> : null}
              </div>
              <div className="campaign-preview-pages">
                {fields.slice(0, 4).map((field, index) => {
                  const options = field.optionsText
                    .split(/[\n,]/)
                    .map((option) => option.trim())
                    .filter(Boolean);
                  const previewOptions = options.length ? options.slice(0, 4) : ["Si", "No"];
                  return (
                    <section className="campaign-preview-question" key={`${field.id}-preview-${index}`}>
                      <div className="campaign-preview-question-head">
                        <span>{index + 1}/{fields.length}</span>
                        {field.required ? <small>Required</small> : null}
                      </div>
                      <strong>{field.label.trim() || `Field ${index + 1}`}</strong>
                      {field.placeholder ? <em>{field.placeholder}</em> : null}
                      {(field.type === "select" || field.type === "multi_select" || field.type === "yes_no") ? (
                        <div className="campaign-preview-options">
                          {previewOptions.map((option) => <span key={`${field.id}-${option}`}>{option}</span>)}
                        </div>
                      ) : (
                        <div className={`campaign-preview-input ${field.type === "textarea" ? "is-long" : ""}`} />
                      )}
                    </section>
                  );
                })}
                {fields.length > 4 ? (
                  <div className="campaign-preview-more">
                    {fields.length - 4} more questions in this form
                  </div>
                ) : null}
              </div>
              <div className="campaign-preview-foot">
                <button type="button" className="ct-btn" disabled>
                  <Check size={13} weight="bold" />
                  {campaignPresentationPayload(presentation).submit_label}
                </button>
                <span>Draft preview</span>
              </div>
            </section>

            <section className="campaign-summary-card">
              <strong>Campaign summary</strong>
              <dl>
                <div><dt>Status</dt><dd>{humanize(campaignStatus)}</dd></div>
                <div><dt>Budget</dt><dd>{dailyBudget ? `USD ${dailyBudget}` : "-"}</dd></div>
                <div><dt>Locations</dt><dd>{campaignLocations.length ? `${campaignLocations.length} saved` : "-"}</dd></div>
                <div><dt>Client</dt><dd>{clientMode === "existing" ? (selectedClient?.display_name || "Existing") : (newClientName.trim() || "New client")}</dd></div>
                <div><dt>Form fields</dt><dd>{fields.length} fields</dd></div>
                <div><dt>Creative</dt><dd>{creativeSummary ? "Copy ready" : "Empty"}</dd></div>
                <div><dt>Meta event</dt><dd>{metaEventsEnabled ? "Lead" : "Off"}</dd></div>
                <div><dt>Optimize</dt><dd>{metaOptimizeForPixel ? "Pixel Lead" : "Off"}</dd></div>
              </dl>
            </section>

          </aside>
        </form>
      ) : null}

      {!isCreateView && showCampaignEmpty ? (
        <section className="campaign-empty-launchpad" aria-label="Create first campaign">
          <div className="campaign-empty-mark" aria-hidden="true">
            <Megaphone size={34} weight="duotone" />
          </div>
          <div className="campaign-empty-copy">
            <span>Owned forms</span>
            <strong>Create the first campaign</strong>
            <p>Targeting, client, creative media and the lead form live in one clean flow.</p>
          </div>
          <button type="button" className="ct-btn campaign-empty-primary" onClick={openCreateView}>
            <Plus size={16} weight="bold" />
            Create campaign
          </button>
          <div className="campaign-empty-chips" aria-hidden="true">
            <span>Targeting</span>
            <span>Media</span>
            <span>Lead form</span>
            <span>Meta Lead</span>
          </div>
        </section>
      ) : !isCreateView ? (
        <div className="campaign-manager-grid">
          <div className="campaign-list">
            {loading && !campaigns.length ? (
              <CtEmptyState compact loading title="Loading campaigns" message="Checking owned forms." />
            ) : campaigns.length ? (
              campaigns.map(renderCampaignCard)
            ) : <CtEmptyState compact title="No campaign forms yet" message="Create the first owned form." />}
          </div>

          <div className="campaign-detail-panel">
            {selectedCampaign ? (
              <>
              <div className="campaign-detail-head">
                <div>
                  <span>Public form</span>
                  <strong>{selectedCampaign.name}</strong>
                  <a href={selectedCampaign.public_url} target="_blank" rel="noreferrer">{selectedCampaign.public_url}</a>
                </div>
                <div className="campaign-detail-actions">
                  <button type="button" className="ct-icon-btn" onClick={() => void copyCampaignUrl(selectedCampaign)} title="Copy public URL" aria-label="Copy public URL">
                    <Copy size={14} weight="bold" />
                  </button>
                  <button type="button" className="ct-icon-btn" onClick={() => window.open(selectedCampaign.public_url, "_blank", "noopener,noreferrer")} title="Open public form" aria-label="Open public form">
                    <ArrowSquareOut size={14} weight="bold" />
                  </button>
                </div>
              </div>

              <div className="campaign-detail-metrics">
                <span><strong>{compactNumber(selectedCampaign.submission_count)}</strong>Submissions</span>
                <span><strong>{selectedCampaign.daily_budget_usd ? `$${selectedCampaign.daily_budget_usd}` : "-"}</strong>Daily</span>
                <span><strong>{selectedCampaignDelivery.enabled ? "On" : "Off"}</strong>Delivery</span>
                <span><strong>{selectedCampaign.meta_events_enabled ? "On" : "Off"}</strong>Meta</span>
              </div>

              <div className="campaign-detail-controls">
                {selectedCampaign.status === "archived" ? (
                  <button type="button" className="ct-btn ct-btn-ghost" disabled={saving} onClick={() => confirmCampaignStatusChange(selectedCampaign, "paused")}>Restore</button>
                ) : (
                  <>
                    <button type="button" className="ct-btn ct-btn-ghost" disabled={saving || selectedCampaign.status === "active"} onClick={() => confirmCampaignStatusChange(selectedCampaign, "active")}>Activate</button>
                    <button type="button" className="ct-btn ct-btn-ghost" disabled={saving || selectedCampaign.status === "paused"} onClick={() => confirmCampaignStatusChange(selectedCampaign, "paused")}>Pause</button>
                  </>
                )}
                <button type="button" className="ct-btn ct-btn-ghost" disabled={saving} onClick={() => deleteCampaign(selectedCampaign)}>
                  <Trash size={13} weight="bold" />
                  Delete
                </button>
                <button type="button" className="ct-btn ct-btn-ghost" disabled={saving || selectedCampaign.status === "archived"} onClick={() => requestRefreshDeliverySource(selectedCampaign)}>Delivery source</button>
              </div>

              {selectedCampaign.meta_plan_graph ? (
                <section className="campaign-plan-readonly">
                  <div className="campaign-submissions-head">
                    <strong>Meta plan</strong>
                    <span>
                      {campaignMetaPlanCounts(selectedCampaign.meta_plan_graph).campaigns} campaigns · {campaignMetaPlanCounts(selectedCampaign.meta_plan_graph).adSets} ad sets · {campaignMetaPlanCounts(selectedCampaign.meta_plan_graph).ads} ads
                    </span>
                  </div>
                  <div className="campaign-plan-readonly-tree">
                    {selectedCampaign.meta_plan_graph.campaigns.map((campaign) => (
                      <article key={campaign.id}>
                        <div>
                          <span>Campaign</span>
                          <strong>{campaign.name}</strong>
                          <small>{campaign.budget_daily_usd ? `USD ${campaign.budget_daily_usd}` : "No budget"} · {humanize(campaign.status)}</small>
                        </div>
                        {campaign.ad_sets.map((adSet) => (
                          <div className="campaign-plan-readonly-adset" key={adSet.id}>
                            <span>Ad set · {humanize(adSet.destination_type)}</span>
                            <strong>{adSet.name}</strong>
                            <small>{adSet.ads.length} ads · {humanize(adSet.optimization_goal)}</small>
                          </div>
                        ))}
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}

              <section className="campaign-media-panel">
                <div className="campaign-submissions-head">
                  <strong>Ad media</strong>
                  <span>{compactNumber(selectedCampaignMedia.length)} files</span>
                </div>
                {selectedCampaignMedia.length ? (
                  <div className="campaign-media-grid">
                    {selectedCampaignMedia.map((media) => (
                      <article className="campaign-media-card" key={media.key}>
                        <div className="campaign-media-preview">
                          {media.media_url && media.asset_type === "image" ? (
                            <img src={media.media_url} alt={media.name} loading="lazy" />
                          ) : media.media_url && media.asset_type === "video" ? (
                            <video src={media.media_url} controls playsInline preload="metadata" />
                          ) : (
                            <Camera size={22} weight="bold" />
                          )}
                          {media.media_url ? (
                            <button type="button" className="ct-icon-btn campaign-media-open" onClick={() => window.open(media.media_url, "_blank", "noopener,noreferrer")} aria-label="Open ad media">
                              <ArrowSquareOut size={13} weight="bold" />
                            </button>
                          ) : null}
                        </div>
                        <div className="campaign-media-meta">
                          <strong>{media.name}</strong>
                          <span>{humanize(media.asset_type)} · {humanize(media.source)}</span>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <CtEmptyState compact title="No ad media" message="Uploaded images and videos will appear here." />
                )}
              </section>

              <section className="campaign-delivery-panel">
                <div className="campaign-submissions-head">
                  <strong>Delivery</strong>
                  <label className="campaign-delivery-mini-toggle">
                    <span>{selectedCampaignDelivery.enabled ? "On" : "Off"}</span>
                    <input
                      type="checkbox"
                      checked={selectedCampaignDelivery.enabled}
                      disabled={saving}
                      onChange={(event) => {
                        const enabled = event.target.checked;
                        confirmCampaignDeliveryConfigChange(
                          selectedCampaign,
                          { ...selectedCampaignDelivery, enabled },
                          `${enabled ? "Enable" : "Disable"} automatic Delivery for future public submissions.`,
                          enabled ? "Enable Delivery" : "Disable Delivery",
                        );
                      }}
                    />
                  </label>
                </div>
                <div className="campaign-delivery-current">
                  <div className="campaign-delivery-current-head">
                    <strong>Current contacts</strong>
                    <button type="button" className="ct-btn ct-btn-ghost" disabled={saving || selectedCampaign.status === "archived"} onClick={() => setShowDetailDeliveryAdd((open) => !open)}>
                      <Plus size={13} weight="bold" />
                      Contact
                    </button>
                  </div>
                  <div className="campaign-delivery-contact-list">
                    {selectedCampaignDelivery.contacts.map((contact) => {
                      const displayContact = campaignDeliveryDisplayContact(contact, selectedCampaign.client);
                      return (
                        <article className="campaign-delivery-contact-card" key={contact.id}>
                          <div>
                            <strong>{displayContact.label}</strong>
                            <span>{campaignDeliveryContactPhoneLabel(displayContact)}</span>
                          </div>
                          <button
                            type="button"
                            className="ct-icon-btn"
                            disabled={saving || selectedCampaign.status === "archived"}
                            onClick={() => removeCampaignDeliveryContact(selectedCampaign, contact.id)}
                            aria-label={`Remove ${displayContact.label}`}
                          >
                            <X size={12} weight="bold" />
                          </button>
                        </article>
                      );
                    })}
                  </div>
                </div>
                {showDetailDeliveryAdd ? (
                  <div className="campaign-delivery-add-panel">
                    {selectedCampaignDeliverySuggestions.length ? (
                      <div className="campaign-delivery-suggestion-grid">
                        {selectedCampaignDeliverySuggestions.map((contact) => (
                          <button type="button" key={contact.id} disabled={saving} onClick={() => addCampaignDeliveryPresetContact(selectedCampaign, contact)}>
                            <span>{contact.label}</span>
                            <small>{campaignDeliveryContactPhoneLabel(contact)}</small>
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <div className="campaign-delivery-custom">
                      <label className="ct-field">
                        <span>Name</span>
                        <input value={detailDeliveryName} onChange={(event) => setDetailDeliveryName(event.target.value)} placeholder="Delivery contact" />
                      </label>
                      <label className="ct-field">
                        <span>Phone</span>
                        <input value={detailDeliveryPhone} onChange={(event) => setDetailDeliveryPhone(event.target.value)} inputMode="tel" placeholder="549..." />
                      </label>
                      <button type="button" className="ct-btn ct-btn-ghost" disabled={saving} onClick={() => addDetailDeliveryCustomContact(selectedCampaign)}>
                        <Plus size={13} weight="bold" />
                        Add
                      </button>
                    </div>
                  </div>
                ) : null}
              </section>

              <div className="campaign-submissions">
                <div className="campaign-submissions-head">
                  <strong>Submissions</strong>
                  <button type="button" className="ct-btn ct-btn-ghost" disabled={submissionsLoading} onClick={() => void loadCampaignSubmissions(selectedCampaign.id)}>
                    <ArrowsClockwise size={13} weight="bold" />
                    Refresh
                  </button>
                </div>
                {submissionsLoading && !submissions.length ? (
                  <CtEmptyState compact loading title="Loading submissions" message="Checking captured leads." />
                ) : submissions.length ? (
                  <div className="campaign-submission-sheet">
                    <table>
                      <thead>
                        <tr>
                          <th>Fecha</th>
                          <th>Nombre</th>
                          <th>WhatsApp</th>
                          <th>Email</th>
                          <th>Delivery</th>
                        </tr>
                      </thead>
                      <tbody>
                        {submissions.map((submission) => (
                          <tr key={submission.id}>
                            <td>{submission.created_at ? shortDate(submission.created_at) : "-"}</td>
                            <td>{submission.full_name || "-"}</td>
                            <td>{campaignSubmissionPhoneLabel(submission)}</td>
                            <td>{submission.email || "-"}</td>
                            <td>
                              <div className="campaign-submission-delivery">
                                {(submission.delivery_statuses?.length ? submission.delivery_statuses : [{ delivery_id: "", source_id: "", recipient_name: "", recipient_phone: "", delivery_status: submission.delivery_status }]).map((status, index) => (
                                  <span
                                    className="delivery-status-pill"
                                    data-tone={status.delivery_status === "pending" ? "warn" : status.delivery_status === "delivered" || status.delivery_status === "sent" ? "success" : status.delivery_status === "failed" || status.delivery_status === "blocked" ? "danger" : "muted"}
                                    key={`${submission.id}-${status.delivery_id || index}`}
                                  >
                                    {status.recipient_name ? `${status.recipient_name}: ` : ""}{humanize(status.delivery_status || "queued")}
                                  </span>
                                ))}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <CtEmptyState compact title="No submissions yet" message="Captured leads will appear here." />
                )}
              </div>
              </>
            ) : (
              <CtEmptyState compact title="No selected campaign" message="Create or select a campaign form." />
            )}
          </div>
        </div>
      ) : null}
      {campaignConfirmDialog ? (
        <ConfirmDialog
          dialog={campaignConfirmDialog}
          busy={saving}
          onClose={closeCampaignConfirmDialog}
          onSubmit={submitCampaignConfirmDialog}
        />
      ) : null}
    </section>
  );
}
