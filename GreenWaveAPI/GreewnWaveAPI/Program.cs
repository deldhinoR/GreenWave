using AutoMapper;
using GreenWaveAPI.Application.Features.Traffic.Commands;
using GreenWaveAPI.Application.Interfaces;
using GreenWaveAPI.Infrastructure.Services;
using GreenWaveAPI.Mapper.AutoMapper;
using MediatR;

var builder = WebApplication.CreateBuilder(args);

// Server binding toggle (LAN vs local)
var bindAll = bool.TryParse(builder.Configuration["Server:BindAll"], out var bindAllParsed) && bindAllParsed;
var httpPort = int.TryParse(builder.Configuration["Server:HttpPort"], out var httpPortParsed) ? httpPortParsed : 5185;
if (bindAll)
{
    builder.WebHost.UseUrls($"http://0.0.0.0:{httpPort}");
}

// Controllers
builder.Services.AddControllers();

// CORS (for calling API from another machine/browser in LAN)
const string LanCorsPolicy = "LanCorsPolicy";
var allowAnyOrigin = bool.TryParse(builder.Configuration["Cors:AllowAnyOrigin"], out var anyOriginParsed) && anyOriginParsed;
var allowedOrigins = builder.Configuration.GetSection("Cors:AllowedOrigins").Get<string[]>() ?? Array.Empty<string>();
builder.Services.AddCors(options =>
{
    options.AddPolicy(LanCorsPolicy, policy =>
    {
        if (allowAnyOrigin)
        {
            policy.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod();
        }
        else if (allowedOrigins.Length > 0)
        {
            policy.WithOrigins(allowedOrigins).AllowAnyHeader().AllowAnyMethod();
        }
    });
});

// AutoMapper
builder.Services.AddAutoMapper(typeof(TrafficMappingProfile));

// MediatR
builder.Services.AddMediatR(typeof(CreateTrafficCommandRequest).Assembly);

builder.Services.AddHttpClient<ISumoService, SumoService>();


// Dependency Injection
builder.Services.AddScoped<IFileService, FileService>();
builder.Services.AddScoped<ISumoService, SumoService>();

// Swagger
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

var app = builder.Build();

// Swagger Middleware
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

// HTTPS redirection toggle
var enableHttpsRedirection = bool.TryParse(builder.Configuration["Server:EnableHttpsRedirection"], out var httpsParsed) && httpsParsed;
if (enableHttpsRedirection)
{
    app.UseHttpsRedirection();
}
app.UseCors(LanCorsPolicy);
app.UseAuthorization();

app.MapControllers();

app.Run();

//budur evde deneme için
// app.Run("http://0.0.0.0:5185");


